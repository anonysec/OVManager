import { useRef, useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import { FiCalendar, FiCheckCircle, FiCopy, FiPlus } from 'react-icons/fi';
import Modal from './Modal';
import { Button, Field } from './ui';
import { copyText } from '../utils/clipboard';
import { userApiPath } from '../utils/userIdentifier';

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

const localDate = (date = new Date()) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

const addDaysLocal = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return localDate(date);
};

const daysUntilLocal = (value: string) => {
  if (!value) return '';
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day) return '';
  const target = new Date(year, month - 1, day);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return String(Math.max(0, Math.ceil((target.getTime() - today.getTime()) / 86400000)));
};

const DATE_SHORTCUTS: [string, number][] = [['1d', 1], ['7d', 7], ['30d', 30], ['90d', 90]];

const UserFormModal = ({ user, isOpen, onClose, onSaved, defaults, linkForUser }: { user?: any; isOpen?: any; onClose?: any; onSaved?: any; defaults?: any; linkForUser?: any }) => {
  const isEdit = !!user;
  const days = Number(defaults?.days) || 0;
  const defaultLogins = String(defaults?.maxLogins ?? 0);
  const [name, setName] = useState('');
  const [expiryMode, setExpiryMode] = useState<'days' | 'date'>('days');
  const [expiryDays, setExpiryDays] = useState(days > 0 ? String(days) : '');
  const [expiryDate, setExpiryDate] = useState(days > 0 ? addDaysLocal(days) : '');
  const [totalTraffic, setTotalTraffic] = useState('');
  const [maxLogins, setMaxLogins] = useState(defaultLogins);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [createdUser, setCreatedUser] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const dateRef = useRef<HTMLInputElement>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (isEdit && user) {
      const date = (user.expiry_date || '').slice(0, 10);
      setExpiryDate(date);
      setExpiryDays(date ? daysUntilLocal(date) : '');
      setExpiryMode(date ? 'date' : 'days');
      setTotalTraffic(gbFromBytes(user.total));
      setMaxLogins(user.max_logins === null || user.max_logins === undefined ? '0' : user.max_logins.toString());
      setError('');
    } else if (!isEdit && isOpen) {
      setName('');
      setExpiryMode('days');
      setExpiryDays(days > 0 ? String(days) : '');
      setExpiryDate(days > 0 ? addDaysLocal(days) : '');
      setTotalTraffic('');
      setMaxLogins(defaultLogins);
      setCreatedUser(null);
      setCopied(false);
      setError('');
    }
  }, [user, isOpen, isEdit, days, defaultLogins]);

  const reset = () => {
    setName('');
    setExpiryMode('days');
    setExpiryDays(days > 0 ? String(days) : '');
    setExpiryDate(days > 0 ? addDaysLocal(days) : '');
    setTotalTraffic('');
    setMaxLogins(defaultLogins);
    setError('');
    setCreatedUser(null);
    setCopied(false);
  };

  const switchExpiryMode = (mode: 'days' | 'date') => {
    if (mode === expiryMode) return;
    if (mode === 'date') {
      const fromDays = expiryDays.trim() !== '' && Number(expiryDays) > 0 ? addDaysLocal(Number(expiryDays)) : expiryDate;
      setExpiryDate(fromDays);
    } else {
      setExpiryDays(daysUntilLocal(expiryDate));
    }
    setExpiryMode(mode);
  };

  const openDatePicker = () => {
    const fromDays = expiryDays.trim() !== '' && Number(expiryDays) > 0 ? addDaysLocal(Number(expiryDays)) : expiryDate;
    setExpiryDate(fromDays);
    setExpiryMode('date');
    requestAnimationFrame(() => {
      const input = dateRef.current as any;
      if (!input) return;
      try {
        input.showPicker?.();
      } catch {
        input.focus();
      }
    });
  };

  const handleClose = () => {
    onClose();
  };

  const handleSubmit = async (e: any) => {
    if (isLoading) return;
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      let resolvedExpiry = expiryDate;
      if (expiryMode === 'days') {
        const daysValue = expiryDays.trim() === '' ? 0 : Number(expiryDays);
        if (!Number.isInteger(daysValue) || daysValue < 0) {
          setError(t('expiryDaysInvalid', 'Enter a whole number of days, or leave it empty for no expiry.'));
          return;
        }
        resolvedExpiry = daysValue > 0 ? addDaysLocal(daysValue) : '';
      }
      const parsedLogins = parseInt(maxLogins, 10);
      const payload = {
        name: isEdit ? user.name : name,
        expiry_date: resolvedExpiry,
        total: bytesFromGB(totalTraffic),
        max_logins: Number.isNaN(parsedLogins) ? 0 : parsedLogins,
      };
      const response = isEdit
        ? await apiClient.put(userApiPath(user), payload)
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
  const pastDate = expiryMode === 'date' && expiryDate !== '' && expiryDate < localDate();

  const handleCopyLink = async () => {
    const ok = createdLink ? await copyText(createdLink) : false;
    setCopied(Boolean(ok));
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={isEdit ? t('updateUser', 'Update user') : t('addUser', 'Add user')}
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
                onChange={isEdit ? undefined : (e) => setName(e.target.value)}
                required={!isEdit}
                minLength={isEdit ? undefined : 3}
                maxLength={64}

                disabled={isEdit}
                placeholder={t('usernameHint', '3–64 characters.')}
                aria-invalid={Boolean(error) || undefined}
                aria-describedby={!isEdit ? 'uf-username-hint' : undefined}
              />
            </div>
            {!isEdit && <p className="ui-field-hint" id="uf-username-hint">{t('usernameFootnote', 'Usernames can’t be changed after creation.')}</p>}
          </div>

          <div className="ui-field uf-expiry">
            <div className="uf-expiry-head">
              <label className="ui-field-label" htmlFor={expiryMode === 'days' ? 'uf-expiry-days' : 'uf-expiry-date'}>
                {t('modal_expiryDate')}
              </label>
              <div className="uf-expiry-modes" role="group" aria-label={t('modal_expiryMode', 'Expiry format')}>
                <button
                  type="button"
                  className={`uf-expiry-mode${expiryMode === 'days' ? ' is-active' : ''}`}
                  aria-pressed={expiryMode === 'days'}
                  onClick={() => switchExpiryMode('days')}
                >
                  {t('expiryDaysMode', 'Days')}
                </button>
                <button
                  type="button"
                  className={`uf-expiry-mode${expiryMode === 'date' ? ' is-active' : ''}`}
                  aria-pressed={expiryMode === 'date'}
                  onClick={() => switchExpiryMode('date')}
                >
                  {t('expiryDateMode', 'Date')}
                </button>
              </div>
            </div>
            <div className="ui-field-control">
              {expiryMode === 'days' ? (
                <div className="uf-expiry-row">
                  <input
                    id="uf-expiry-days"
                    className="ui-input"
                    type="number"
                    min="0"
                    step="1"
                    value={expiryDays}
                    onChange={(e) => setExpiryDays(e.target.value)}
                    placeholder={t('expiryDaysPlaceholder', 'e.g. 30')}
                  />
                  <span className="uf-expiry-suffix">{t('expiryDaysSuffix', 'days')}</span>
                  <button type="button" className="uf-expiry-calendar" aria-label={t('expiryPickDate', 'Pick a date')} onClick={openDatePicker}>
                    <FiCalendar size={16} aria-hidden="true" />
                  </button>
                </div>
              ) : (
                <div className="uf-expiry-row">
                  <input
                    id="uf-expiry-date"
                    ref={dateRef}
                    className="ui-input"
                    type="date"
                    value={expiryDate}
                    onChange={(e) => setExpiryDate(e.target.value)}
                  />
                  <button type="button" className="uf-expiry-calendar" aria-label={t('expiryPickDate', 'Pick a date')} onClick={openDatePicker}>
                    <FiCalendar size={16} aria-hidden="true" />
                  </button>
                </div>
              )}
            </div>
            <div className="uf-chips" role="group" aria-label={t('modal_expiryShortcuts', 'Expiry shortcuts')}>
              {DATE_SHORTCUTS.map(([label, count]) => (
                <Button
                  key={label}
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setExpiryMode('days');
                    setExpiryDays(String(count));
                    setExpiryDate('');
                  }}
                >
                  +{label}
                </Button>
              ))}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setExpiryMode('days');
                  setExpiryDays('');
                  setExpiryDate('');
                }}
              >
                {t('expiryNever', 'Never')}
              </Button>
            </div>
            <p className="ui-field-hint">
              {expiryMode === 'days'
                ? t('expiryHintDays', 'Leave empty for no expiry.')
                : t('expiryHintDate', 'Leave empty for no expiry, or type YYYY-MM-DD.')}
            </p>
            {pastDate && <p className="ui-field-hint uf-expiry-warn">{t('expiryPastDate', 'That date is in the past.')}</p>}
          </div>

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
              <button type="button" className={`uf-devices-card${maxLogins === '0' || maxLogins === '' ? ' is-active' : ''}`} aria-pressed={maxLogins === '0' || maxLogins === ''} onClick={() => setMaxLogins('0')}>∞</button>
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
