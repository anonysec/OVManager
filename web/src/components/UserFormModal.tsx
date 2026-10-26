import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import { FiCheckCircle, FiCopy, FiPlus } from 'react-icons/fi';
import Modal from './Modal';
import { Button, Field } from './ui';
import { copyText } from '../utils/clipboard';

const bytesFromGB = (value: any) => {
  const cleaned = value?.toString().trim();
  if (!cleaned) return null; // empty -> unlimited
  const parsed = parseFloat(cleaned);
  if (Number.isNaN(parsed) || parsed <= 0) return null; // 0 / invalid -> unlimited
  return Math.round(parsed * 1024 * 1024 * 1024);
};

const gbFromBytes = (bytes: any) => {
  if (bytes === null || bytes === undefined) return '';
  const gb = Number(bytes) / 1024 / 1024 / 1024;
  if (!Number.isFinite(gb)) return '';
  return parseFloat(gb.toFixed(2)).toString().replace(/\.00$/, '');
};

const parseError = (err: any, fallback: any) => {
  const detail = err.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map((d: any) => d.msg || JSON.stringify(d)).join(', ');
  }
  if (typeof detail === 'object' && detail !== null) {
    return JSON.stringify(detail);
  }
  return detail || fallback;
};

const defaultExpiryDate = (days = 30) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
};

const DATE_SHORTCUTS: [string, number][] = [['1d', 1], ['7d', 7], ['1m', 30], ['2m', 60]];

const UserFormModal = ({ user, isOpen, onClose, onSaved, defaults, linkForUser }: { user?: any; isOpen?: any; onClose?: any; onSaved?: any; defaults?: any; linkForUser?: any }) => {
  const isEdit = !!user;
  const days = Number(defaults?.days) || 30;
  const defaultLogins = String(defaults?.maxLogins ?? 1);
  const [name, setName] = useState('');
  const [expiryDate, setExpiryDate] = useState(defaultExpiryDate(days));
  const [totalTraffic, setTotalTraffic] = useState('');
  const [maxLogins, setMaxLogins] = useState(defaultLogins);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [createdUser, setCreatedUser] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const { t } = useTranslation();

  useEffect(() => {
    if (isEdit && user) {
      if (user.expiry_date) {
        const date = new Date(user.expiry_date);
        setExpiryDate(date.toISOString().split('T')[0]);
      } else {
        setExpiryDate('');
      }
      setTotalTraffic(gbFromBytes(user.total));
      setMaxLogins(user.max_logins === null || user.max_logins === undefined ? '1' : user.max_logins.toString());
      setError('');
    } else if (!isEdit && isOpen) {
      setName('');
      setExpiryDate(defaultExpiryDate(days));
      setTotalTraffic('');
      setMaxLogins(defaultLogins);
      setCreatedUser(null);
      setCopied(false);
      setError('');
    }
  }, [user, isOpen, isEdit, days, defaultLogins]);

  const reset = () => { setName(''); setExpiryDate(defaultExpiryDate(days)); setTotalTraffic(''); setMaxLogins(defaultLogins); setError(''); setCreatedUser(null); setCopied(false); };

  const handleClose = () => {
    if (!isEdit) reset();
    onClose();
  };

  const handleSubmit = async (e: any) => {
    if (isLoading) return;
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const parsedLogins = parseInt(maxLogins, 10);
      const payload = {
        name: isEdit ? user.name : name,
        expiry_date: expiryDate,
        total: bytesFromGB(totalTraffic),
        max_logins: Number.isNaN(parsedLogins) ? 1 : parsedLogins,
      };
      const response = isEdit
        ? await apiClient.put(`/users/${user.uuid}`, payload)
        : await apiClient.post('/users/', payload);
      if (response.data.success) {
        if (!isEdit) {
          onSaved();
          const created = response.data?.data;
          if (created?.uuid) {
            setCreatedUser(created);
          } else {
            reset();
          }
        } else {
          onSaved();
          onClose();
        }
      } else {
        setError(response.data.msg || t(isEdit ? 'userUpdateFailed' : 'userCreateFailed'));
      }
    } catch (err: any) {
      setError(parseError(err, t(isEdit ? 'userUpdateFailed' : 'userCreateFailed')));
    } finally {
      setIsLoading(false);
    }
  };

  const createdLink = createdUser && linkForUser ? linkForUser(createdUser) : '';

  const handleCopyLink = async () => {
    const ok = createdLink ? await copyText(createdLink) : false;
    setCopied(Boolean(ok));
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size="medium"
    >
      {createdUser && (
        <div className="uf-created" role="status">
          <FiCheckCircle className="uf-created-icon" aria-hidden="true" />
          <h3 className="uf-created-title">{createdUser.name}</h3>
          <p className="uf-created-note">
            {t('createdNote', 'Hand the profile to the customer — the VPN config is generated on first download.')}
          </p>
          <div className="uf-created-actions">
            <Button
              variant="primary"
              icon={<FiCopy size={14} aria-hidden="true" />}
              onClick={handleCopyLink}
              disabled={!createdLink}
            >
              {copied ? t('createdCopied', 'Link copied') : t('createdCopyLink', 'Copy subscription link')}
            </Button>
          </div>
          <div className="uf-footer">
            <Button variant="ghost" onClick={handleClose}>{t('createdDone', 'Done')}</Button>
          </div>
        </div>
      )}
      {!createdUser && (
      <form onSubmit={handleSubmit} className="uf-form">
        <div className="uf-grid">
          <div className="ui-field uf-username-hero">
            <label className="ui-field-label" htmlFor="uf-username">
              {t('username')}
              {!isEdit && <span className="ui-field-required" aria-hidden="true">*</span>}
            </label>
            <div className="ui-field-control uf-name-row">
              <input
                id="uf-username"
                className="ui-input"
                type="text"
                value={isEdit ? (user?.name || '') : name}
                onChange={(e) => setName(e.target.value)}
                required={!isEdit}
                minLength={isEdit ? undefined : 3}
                maxLength={64}
                autoFocus={!isEdit}
                disabled={isEdit}
                placeholder={t('usernameHint', '3–64 characters.')}
                aria-invalid={Boolean(error) || undefined}
                aria-describedby={!isEdit ? 'uf-username-hint' : undefined}
              />
            </div>
            {!isEdit && <p className="ui-field-hint" id="uf-username-hint">{t('usernameFootnote', 'Usernames can’t be changed after creation.')}</p>}
          </div>

          <Field label={t('modal_expiryDate')} required>
            <input
              type="date"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
              className="ui-input uf-date"
            />
            <div className="uf-chips" role="group" aria-label={t('modal_expiryDate')}>
              {DATE_SHORTCUTS.map(([label, days]) => (
                <Button
                  key={label}
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const d = new Date();
                    d.setDate(d.getDate() + days);
                    setExpiryDate(d.toISOString().split('T')[0]);
                  }}
                >
                  +{label}
                </Button>
              ))}
            </div>
          </Field>

          <Field label={t('modal_totalTraffic')} hint={t('modal_totalTrafficHint')}>
            <input
              type="number"
              value={totalTraffic}
              onChange={(e) => setTotalTraffic(e.target.value)}
              min="0"
              step="0.01"
              placeholder={t('modal_totalTrafficPlaceholder')}
              title={t('modal_totalTrafficHint')}
            />
          </Field>

          <div className="uf-devices">
            <Field label={t('modal_maxLogins')} hint={t('modal_maxLoginsHint')}>
              <input
                type="number"
                value={maxLogins}
                onChange={(e) => setMaxLogins(e.target.value)}
                min="0"
                step="1"
                placeholder={t('modal_maxLoginsPlaceholder')}
                title={t('modal_maxLoginsHint')}
              />
            </Field>
            <div className="uf-devices-cards" role="group" aria-label={t('modal_maxLogins')}>
              <button type="button" className={`uf-devices-card${maxLogins === '1' ? ' is-active' : ''}`} aria-pressed={maxLogins === '1'} onClick={() => setMaxLogins('1')}>1</button>
              <button type="button" className={`uf-devices-card${maxLogins === '2' ? ' is-active' : ''}`} aria-pressed={maxLogins === '2'} onClick={() => setMaxLogins('2')}>2</button>
              <button type="button" className={`uf-devices-card${maxLogins === '0' ? ' is-active' : ''}`} aria-pressed={maxLogins === '0'} onClick={() => setMaxLogins('0')}>∞</button>
            </div>
          </div>
        </div>

        {error && <p className="uf-error" role="alert">{error}</p>}

        <div className="uf-footer">
          <Button variant="ghost" onClick={handleClose}>{t('cancelButton')}</Button>
          <Button type="submit" variant="primary" loading={isLoading} icon={<FiPlus size={14} aria-hidden="true" />}>
            {isEdit ? t('updateUserButton', 'Update User') : t('createUserButton')}
          </Button>
        </div>
      </form>
      )}
    </Modal>
  );
};

export default UserFormModal;
