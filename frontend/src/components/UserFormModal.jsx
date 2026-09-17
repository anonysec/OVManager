import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import { FiPlus, FiZap } from 'react-icons/fi';
import Modal from './Modal';
import { Button, Field } from './ui';

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

const defaultExpiryDate = () => {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().split('T')[0];
};

const DATE_SHORTCUTS = [['1d', 1], ['7d', 7], ['1m', 30], ['2m', 60]];

// Unified add/edit user form. mode="create" (user=null) or mode="edit".
// Fields are grouped into Account / Validity / Limits so the form reads as
// three small decisions instead of one long column. Create defaults to a
// 30-day expiry and a single device, both one click away from any value.
const UserFormModal = ({ user, isOpen, onClose, onSaved }) => {
  const isEdit = !!user;
  const [name, setName] = useState('');
  const [expiryDate, setExpiryDate] = useState(defaultExpiryDate);
  const [totalTraffic, setTotalTraffic] = useState('');
  const [maxLogins, setMaxLogins] = useState('1');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [suggest, setSuggest] = useState('');
  const [suggestLoading, setSuggestLoading] = useState(false);
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
      setExpiryDate(defaultExpiryDate());
      setTotalTraffic('');
      setMaxLogins('1');
      setSuggest('');
      setError('');
    }
  }, [user, isOpen, isEdit]);

  const fetchSuggest = async () => {
    setSuggestLoading(true);
    try {
      const res = await apiClient.get('/users/next-username');
      if (res.data?.success && res.data?.data?.username) {
        setSuggest(res.data.data.username);
        return res.data.data.username;
      }
      setSuggest('');
      return '';
    } catch {
      setSuggest('');
      return '';
    } finally {
      setSuggestLoading(false);
    }
  };

  // One click fills the field — no two-step chip dance.
  const handleSuggest = async () => {
    const value = suggest || (await fetchSuggest());
    if (value) setName(value);
  };

  const reset = () => { setName(''); setExpiryDate(defaultExpiryDate()); setTotalTraffic(''); setMaxLogins('1'); setError(''); setSuggest(''); };

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
      };
      const response = isEdit
        ? await apiClient.put(`/users/${user.uuid}`, payload)
        : await apiClient.post('/users/', payload);
      if (response.data.success) {
        if (!isEdit) reset();
        onSaved();
      } else {
        setError(response.data.msg || t(isEdit ? 'userUpdateFailed' : 'userCreateFailed'));
      }
    } catch (err) {
      setError(parseError(err, t(isEdit ? 'userUpdateFailed' : 'userCreateFailed')));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={isEdit ? `${t('modal_editUserTitle', 'Edit User')} — ${user?.name || ''}` : t('modal_createUserTitle')}
      size="medium"
    >
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
              {!isEdit && (
                <Button
                  variant="secondary"
                  onClick={handleSuggest}
                  loading={suggestLoading}
                  icon={<FiZap size={14} aria-hidden="true" />}
                  title={t('suggestUsername', 'Suggest next username')}
                  className="uf-suggest"
                  onMouseEnter={() => { if (!suggest && isOpen) fetchSuggest(); }}
                  onFocus={() => { if (!suggest) fetchSuggest(); }}
                >
                  {suggest ? `${t('suggest', 'Suggest')}: ${suggest}` : t('suggest', 'Suggest')}
                </Button>
              )}
            </div>
            {!isEdit && <p className="ui-field-hint" id="uf-username-hint">{t('usernameHint', '3–64 characters.')}</p>}
          </div>
          {!isEdit && (
            <p className="uf-note">{t('createUserDefaults', 'New users start with 30 days and 1 device — change anything below.')}</p>
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
            </Field>
          </div>
          <div className="uf-chips" role="group" aria-label={t('modal_maxLogins')}>
            <Button size="sm" variant={maxLogins === '1' ? 'primary' : 'ghost'} onClick={() => setMaxLogins('1')}>1</Button>
            <Button size="sm" variant={maxLogins === '2' ? 'primary' : 'ghost'} onClick={() => setMaxLogins('2')}>2</Button>
            <Button size="sm" variant={maxLogins === '0' ? 'primary' : 'ghost'} onClick={() => setMaxLogins('0')}>∞</Button>
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
    </Modal>
  );
};

export default UserFormModal;
