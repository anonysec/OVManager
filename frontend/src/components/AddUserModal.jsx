import { useState } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

const AddUserModal = ({ isOpen, onClose, onUserAdded }) => {
  const [name, setName] = useState('');
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

  const reset = () => { setName(''); setExpiryDate(''); setTotalTraffic(''); setMaxLogins('1'); setError(''); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const total = bytesFromGB(totalTraffic);
      const parsedLogins = parseInt(maxLogins, 10);
      const payload = {
        name: name,
        expiry_date: expiryDate,
        total,
        max_logins: Number.isNaN(parsedLogins) ? 1 : parsedLogins,
      };
      const response = await apiClient.post('/users/', payload);
      if (response.data.success) {
        reset();
        onUserAdded();
      } else {
        setError(response.data.msg);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'An error occurred. The username might already exist.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('modal_createUserTitle')} size="medium">
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="input-group">
          <label htmlFor="new-user-name">{t('username')}</label>
          <input
            type="text"
            id="new-user-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required minLength="3" maxLength="10"
            autoFocus
          />
        </div>
        <div className="input-group">
          <label htmlFor="new-user-expiry">{t('modal_expiryDate')}</label>
          <input
            type="date"
            id="new-user-expiry"
            value={expiryDate}
            onChange={(e) => setExpiryDate(e.target.value)}
            required
          />
        </div>
        <div className="input-group">
          <label htmlFor="new-user-total">{t('modal_totalTraffic')}</label>
          <input
            type="number"
            id="new-user-total"
            value={totalTraffic}
            onChange={(e) => setTotalTraffic(e.target.value)}
            min="0"
            step="0.01"
            placeholder={t('modal_totalTrafficPlaceholder')}
          />
          <small className="input-hint">{t('modal_totalTrafficHint')}</small>
        </div>
        <div className="input-group">
          <label htmlFor="new-user-max-logins">{t('modal_maxLogins')}</label>
          <input
            type="number"
            id="new-user-max-logins"
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
            {t('createUserButton')}
          </LoadingButton>
        </div>
        {error && <p className="error-message">{error}</p>}
      </form>
    </Modal>
  );
};

export default AddUserModal;