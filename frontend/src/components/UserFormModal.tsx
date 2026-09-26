import { useState, useEffect, useCallback } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import { FiCheckCircle, FiCopy, FiDownload, FiPlus, FiZap } from 'react-icons/fi';
import Modal from './Modal';
import { Button, Field } from './ui';
import { copyText } from '../utils/clipboard';

const bytesFromGB = (value) => {
  const cleaned = value?.toString().trim();
  if (!cleaned) return null; // empty -> unlimited
  const parsed = parseFloat(cleaned);
  if (Number.isNaN(parsed) || parsed <= 0) return null; // 0 / invalid -> unlimited
  return Math.round(parsed * 1024 * 1024 * 1024);
};

const gbFromBytes = (bytes) => {
  if (bytes === null || bytes === undefined) return '';
  const gb = Number(bytes) / 1024 / 1024 / 1024;
  if (!Number.isFinite(gb)) return '';
  return parseFloat(gb.toFixed(2)).toString().replace(/\.00$/, '');
};

const parseError = (err, fallback) => {
  const detail = err.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map(d => d.msg || JSON.stringify(d)).join(', ');
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

const DATE_SHORTCUTS = [['1d', 1], ['7d', 7], ['1m', 30], ['2m', 60]];

// Unified add/edit user form. mode="create" (user=null) or mode="edit".
// Fields are grouped into Account / Validity / Limits so the form reads as
// three small decisions instead of one long column. Create defaults come
// from Settings (30 days / 1 device unless configured otherwise), and a
// successful create flips the modal into a handoff step: download the
// profile or copy the subscription link without leaving the screen.
const UserFormModal = ({ user, isOpen, onClose, onSaved, defaults, linkForUser, onDownloadUser }) => {
  const isEdit = !!user;
  const days = Number(defaults?.days) || 30;
  const defaultLogins = String(defaults?.maxLogins ?? 1);
  const [name, setName] = useState('');
  const [tag, setTag] = useState('');
  const [expiryDate, setExpiryDate] = useState(defaultExpiryDate(days));
  const [totalTraffic, setTotalTraffic] = useState('');
  const [maxLogins, setMaxLogins] = useState(defaultLogins);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [suggest, setSuggest] = useState('');
  // `null` = the endpoint is not usable for this account (no username prefix
  // configured) or unreachable — the button then stays hidden instead of
  // sitting there dead. Empty string = not fetched yet.
  const [suggestUnavailable, setSuggestUnavailable] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [createdUser, setCreatedUser] = useState(null);
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
      setTag(user.tag || '');
      setError('');
    } else if (!isEdit && isOpen) {
      setName('');
      setTag('');
      setExpiryDate(defaultExpiryDate(days));
      setTotalTraffic('');
      setMaxLogins(defaultLogins);
      setSuggest('');
      setSuggestUnavailable(false);
      setCreatedUser(null);
      setCopied(false);
      setError('');
    }
  }, [user, isOpen, isEdit, days, defaultLogins]);

  const fetchSuggest = useCallback(async () => {
    setSuggestLoading(true);
    try {
      const res = await apiClient.get('/users/next-username');
      if (res.data?.success && res.data?.data?.username) {
        setSuggest(res.data.data.username);
        setSuggestUnavailable(false);
        return res.data.data.username;
      }
      setSuggest('');
      setSuggestUnavailable(true);
      return '';
    } catch {
      setSuggest('');
      setSuggestUnavailable(true);
      return '';
    } finally {
      setSuggestLoading(false);
    }
  }, []);

  // One click fills the field. Availability is probed once when the modal
  // opens so a dead button never renders.
  useEffect(() => {
    if (!isOpen || isEdit) return undefined;
    setSuggestLoading(true);
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.get('/users/next-username');
        if (cancelled) return;
        if (res.data?.success && res.data?.data?.username) {
          setSuggest(res.data.data.username);
          setSuggestUnavailable(false);
        } else {
          setSuggest('');
          setSuggestUnavailable(true);
        }
      } catch {
        if (!cancelled) { setSuggest(''); setSuggestUnavailable(true); }
      } finally {
        if (!cancelled) setSuggestLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isOpen, isEdit]);

  const handleSuggest = async () => {
    const value = suggest || (await fetchSuggest());
    if (value) setName(value);
  };

  const reset = () => { setName(''); setTag(''); setExpiryDate(defaultExpiryDate(days)); setTotalTraffic(''); setMaxLogins(defaultLogins); setError(''); setSuggest(''); setCreatedUser(null); setCopied(false); };

  const handleClose = () => {
    if (!isEdit) reset();
    onClose();
  };

  const handleSubmit = async (e) => {
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
        tag: tag.trim() || null,
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
    } catch (err) {
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
      title={isEdit ? `${t('modal_editUserTitle', 'Edit User')} — ${user?.name || ''}` : t('modal_createUserTitle')}
      size="medium"
    >
      {createdUser && (
        <div className="uf-created" role="status">
          <FiCheckCircle className="uf-created-icon" aria-hidden="true" />
          <h3 className="uf-created-title">{createdUser.name}{createdUser.tag ? ` · ${createdUser.tag}` : ''}</h3>
          <p className="uf-created-note">
            {t('createdNote', 'Hand the profile to the customer — the VPN config is generated on first download.')}
          </p>
          <div className="uf-created-actions">
            <Button
              variant="primary"
              icon={<FiDownload size={14} aria-hidden="true" />}
              onClick={() => { if (onDownloadUser) { onClose(); onDownloadUser(createdUser); } }}
            >
              {t('downloadConfig', 'Get Config')}
            </Button>
            <Button
              variant="secondary"
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
        <fieldset className="uf-section">
          <legend className="uf-legend">{t('formSectionAccount', 'Account')}</legend>
          <div className="ui-field">
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
                aria-invalid={Boolean(error) || undefined}
                aria-describedby={!isEdit ? 'uf-username-hint' : undefined}
              />
              {!isEdit && !suggestUnavailable && (
                <Button
                  variant="secondary"
                  onClick={handleSuggest}
                  loading={suggestLoading}
                  icon={<FiZap size={14} aria-hidden="true" />}
                  title={t('suggestUsername', 'Suggest next username')}
                  className="uf-suggest"
                >
                  {suggest ? `${t('suggest', 'Suggest')}: ${suggest}` : t('suggest', 'Suggest')}
                </Button>
              )}
            </div>
            {!isEdit && <p className="ui-field-hint" id="uf-username-hint">{t('usernameHint', '3–64 characters.')}</p>}
          </div>
          <Field
            label={t('userTag', 'Label')}
            hint={t('userTagHint', 'Optional — e.g. monthly, vip, reseller-a. Shown as a chip on the user row.')}
          >
            <input
              type="text"
              className="ui-input"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              maxLength={64}
              placeholder={t('userTagPlaceholder', 'monthly, vip, reseller-a…')}
            />
          </Field>
          {!isEdit && (
            <p className="uf-note">{t('createUserDefaults', 'New users start with {{days}} days and {{devices}} device(s) — change anything below.', { days, count: Number(defaultLogins) || 1 })}</p>
          )}
        </fieldset>

        <fieldset className="uf-section">
          <legend className="uf-legend">{t('formSectionValidity', 'Validity')}</legend>
          <Field label={t('modal_expiryDate')} required>
            <input
              type="date"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
              className="uf-date"
            />
          </Field>
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
        </fieldset>

        <fieldset className="uf-section">
          <legend className="uf-legend">{t('formSectionLimits', 'Limits')}</legend>
          <div className="uf-grid">
            <Field label={t('modal_totalTraffic')} hint={t('modal_totalTrafficHint')}>
              <input
                type="number"
                value={totalTraffic}
                onChange={(e) => setTotalTraffic(e.target.value)}
                min="0"
                step="0.01"
                placeholder={t('modal_totalTrafficPlaceholder')}
              />
            </Field>
            <Field label={t('modal_maxLogins')} hint={t('modal_maxLoginsHint')}>
              <input
                type="number"
                value={maxLogins}
                onChange={(e) => setMaxLogins(e.target.value)}
                min="1"
                step="1"
                placeholder={t('modal_maxLoginsPlaceholder')}
              />
              <div className="uf-devices-chips" role="group" aria-label={t('modal_maxLogins')}>
                <button type="button" className={`uf-device-chip${maxLogins === '1' ? ' is-active' : ''}`} onClick={() => setMaxLogins('1')}>1</button>
                <button type="button" className={`uf-device-chip${maxLogins === '2' ? ' is-active' : ''}`} onClick={() => setMaxLogins('2')}>2</button>
                <button type="button" className={`uf-device-chip${maxLogins === '0' ? ' is-active' : ''}`} onClick={() => setMaxLogins('0')}>∞</button>
              </div>
            </Field>
          </div>
        </fieldset>

        {error && <p className="uf-error" role="alert">{error}</p>}

        <div className="uf-footer">
          <Button variant="secondary" onClick={handleClose}>{t('cancelButton')}</Button>
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
