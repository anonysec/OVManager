import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

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

// Unified add/edit user form. mode="create" (user=null) or mode="edit".
// Replaces AddUserModal + EditUserModal, which shared bytes/date/logins
// widgets and error parsing. Create-only: editable name + suggest flow.
// Edit-only: name shown disabled, fields prefilled from the user row.
const UserFormModal = ({ user, isOpen, onClose, onSaved }) => {
  const isEdit = !!user;
  const [name, setName] = useState('');
  const [expiryDate, setExpiryDate] = useState('');
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
      setError('');
    }
  }, [user, isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchSuggest = async () => {
    setSuggestLoading(true);
    try {
      const res = await apiClient.get('/users/next-username');
      if (res.data?.success && res.data?.data?.username) {
        setSuggest(res.data.data.username);
      } else {
        setSuggest('');
      }
    } catch {
      setSuggest('');
    } finally {
      setSuggestLoading(false);
    }
  };

  const reset = () => { setName(''); setExpiryDate(''); setTotalTraffic(''); setMaxLogins('1'); setError(''); setSuggest(''); };

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
        setError(response.data.msg || (isEdit ? 'Failed to update user.' : 'Failed to create user.'));
      }
    } catch (err) {
      setError(parseError(err, isEdit
        ? 'An error occurred while updating the user.'
        : 'An error occurred. The username might already exist.'));
    } finally {
      setIsLoading(false);
    }
  };

  const idp = (s) => `${isEdit ? 'edit-user' : 'new-user'}-${s}`;

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={isEdit ? `${t('modal_editUserTitle', 'Edit User')} — ${user?.name || ''}` : t('modal_createUserTitle')}
      size="medium"
    >
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="input-group">
          <label htmlFor={`${idp('name')}`}>{t('username')}</label>
          {isEdit ? (
            <input type="text" id={`${idp('name')}`} value={user?.name || ''} disabled />
          ) : (
            <>
              <div className="shortcut-row">
                <input
                  type="text"
                  id={`${idp('name')}`}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required minLength="3" maxLength="64"
                  autoFocus
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? `${idp('error')} ${idp('name-hint')}` : `${idp('name-hint')}`}
                  className="shortcut-input"
                />
                <div className="shortcut-btns">
                  <button
                    type="button"
                    className="shortcut-chip"
                    disabled={suggestLoading}
                    onClick={async () => { if (!suggest) await fetchSuggest(); }}
                    onMouseEnter={() => { if (!suggest && isOpen) fetchSuggest(); }}
                    onFocus={() => { if (!suggest) fetchSuggest(); }}
                    title={t('suggestUsername', 'Suggest next username')}
                  >
                    {suggestLoading ? '…' : t('suggest', 'Suggest')}
                  </button>
                  {suggest && (
                    <button type="button" className="shortcut-chip active" onClick={() => setName(suggest)} title={suggest}>
                      {suggest}
                    </button>
                  )}
                </div>
              </div>
              <small id={`${idp('name-hint')}`} className="input-hint">{t('usernameHint', '3–64 characters.')}</small>
            </>
          )}
        </div>
        <div className="input-group">
          <label htmlFor={`${idp('expiry')}`}>{t('modal_expiryDate')}</label>
          <div className="date-input-wrap">
            <input
              type="date"
              id={`${idp('expiry')}`}
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
              required
              className="date-input"
            />
            <div className="date-shortcuts">
              {[['1d', 1], ['7d', 7], ['1m', 30], ['2m', 60]].map(([label, days]) => (
                <button key={label} type="button" className="date-chip" onClick={() => {
                  const d = new Date(); d.setDate(d.getDate() + days);
                  setExpiryDate(d.toISOString().split('T')[0]);
                }}>{label}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="input-group">
          <label htmlFor={`${idp('total')}`}>{t('modal_totalTraffic')}</label>
          <input
            type="number"
            id={`${idp('total')}`}
            value={totalTraffic}
            onChange={(e) => setTotalTraffic(e.target.value)}
            min="0"
            step="0.01"
            placeholder={t('modal_totalTrafficPlaceholder')}
          />
          <small className="input-hint">{t('modal_totalTrafficHint')}</small>
        </div>
        <div className="input-group">
          <label htmlFor={`${idp('max-logins')}`}>{t('modal_maxLogins')}</label>
          <div className="shortcut-row">
            <input
              type="number"
              id={`${idp('max-logins')}`}
              value={maxLogins}
              onChange={(e) => setMaxLogins(e.target.value)}
              min="1"
              step="1"
              placeholder={t('modal_maxLoginsPlaceholder')}
              className="shortcut-input"
            />
            <div className="shortcut-btns">
              <button type="button" className={`shortcut-chip${maxLogins === '1' ? ' active' : ''}`} onClick={() => setMaxLogins('1')}>1</button>
              <button type="button" className={`shortcut-chip${maxLogins === '2' ? ' active' : ''}`} onClick={() => setMaxLogins('2')}>2</button>
              <button type="button" className={`shortcut-chip${maxLogins === '0' ? ' active' : ''}`} onClick={() => setMaxLogins('0')}>∞</button>
            </div>
          </div>
          <small className="input-hint">{t('modal_maxLoginsHint')}</small>
        </div>
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          <LoadingButton isLoading={isLoading} type="submit" className="btn">
            {isEdit ? t('updateUserButton', 'Update User') : t('createUserButton')}
          </LoadingButton>
        </div>
        {error && <p id={`${idp('error')}`} className="error-message" role="alert">{error}</p>}
      </form>
    </Modal>
  );
};

export default UserFormModal;
