import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';

const EditUserModal = ({ user, onClose, onUserUpdated }) => {
  const [expiryDate, setExpiryDate] = useState('');
  const [totalTraffic, setTotalTraffic] = useState('');
  const [maxLogins, setMaxLogins] = useState('1');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation();

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

  useEffect(() => {
    if (user && user.expiry_date) {
      const date = new Date(user.expiry_date);
      const formattedDate = date.toISOString().split('T')[0];
      setExpiryDate(formattedDate);
    }
    if (user) {
      setTotalTraffic(gbFromBytes(user.total));
      setMaxLogins(
        user.max_logins === null || user.max_logins === undefined
          ? '1'
          : user.max_logins.toString()
      );
    }
  }, [user]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);


    const parsedLogins = parseInt(maxLogins, 10);
    const payload = {
      name: user.name,
      expiry_date: expiryDate,
      total: bytesFromGB(totalTraffic),
      max_logins: Number.isNaN(parsedLogins) ? 1 : parsedLogins,
    };

    try {
      const response = await apiClient.put(`/users/${user.uuid}`, payload);
      if (response.data.success) {
        console.warn('User updated successfully.');
        onUserUpdated();
      } else {
        setError(response.data.msg || 'Failed to update user.');
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'An error occurred while updating the user.');
    } finally {
      setIsLoading(false);
    }
  };

  if (!user) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-header">
          <h3>{t('modal_editUserTitle', 'Edit User')} - {user.name}</h3>
          <button onClick={onClose} className="close-modal-btn">&times;</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label htmlFor="edit-user-name">{t('username')}</label>
            <input
              type="text"
              id="edit-user-name"
              value={user.name}
              disabled
            />
          </div>
          <div className="input-group">
            <label htmlFor="edit-user-expiry">{t('modal_expiryDate')}</label>
            <input
              type="date"
              id="edit-user-expiry"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
              required
            />
          </div>
          <div className="input-group">
            <label htmlFor="edit-user-total">{t('modal_totalTraffic')}</label>
            <input
              type="number"
              id="edit-user-total"
              value={totalTraffic}
              onChange={(e) => setTotalTraffic(e.target.value)}
              min="0"
              step="0.01"
              placeholder={t('modal_totalTrafficPlaceholder')}
            />
            <small className="input-hint">{t('modal_totalTrafficHint')}</small>
          </div>
          <div className="input-group">
            <label htmlFor="edit-user-max-logins">{t('modal_maxLogins')}</label>
            <input
              type="number"
              id="edit-user-max-logins"
              value={maxLogins}
              onChange={(e) => setMaxLogins(e.target.value)}
              min="0"
              step="1"
              placeholder={t('modal_maxLoginsPlaceholder')}
            />
            <small className="input-hint">{t('modal_maxLoginsHint')}</small>
          </div>
          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
            <LoadingButton isLoading={isLoading} type="submit" className="btn">
              {t('updateUserButton', 'Update User')}
            </LoadingButton>
          </div>
          {error && <p className="error-message">{error}</p>}
        </form>
      </div>
    </div>
  );
};

export default EditUserModal;