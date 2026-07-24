import { useState } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

const AddAdminModal = ({ isOpen, onClose, onAdminCreated }) => {
  const { t } = useTranslation();
  const [formData, setFormData] = useState({ username: '', password: '', telegram_id: '', username_prefix: '' });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    if (!formData.username || !formData.password) {
      setError(t('fillAllFields'));
      return;
    }
    setIsLoading(true);
    try {
      const payload = {
        username: formData.username,
        password: formData.password,
        telegram_id: formData.telegram_id ? parseInt(formData.telegram_id, 10) : null,
        username_prefix: formData.username_prefix || null,
      };
      const response = await apiClient.post('/admin/', payload);
      if (response.data.success) {
        onAdminCreated();
      } else {
        setError(response.data.msg || t('unableToCreateAdmin'));
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map(d => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setError(JSON.stringify(detail));
      } else {
        setError(detail || t('errorCreatingAdmin'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('addNewAdmin')} size="small">
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="input-group">
          <label htmlFor="username">{t('username')}</label>
          <input type="text" id="username" name="username" value={formData.username} onChange={handleChange} required />
        </div>
        <div className="input-group">
          <label htmlFor="password">{t('password')}</label>
          <input type="password" id="password" name="password" value={formData.password} onChange={handleChange} required />
        </div>
        <div className="input-group">
          <label htmlFor="telegram_id">Telegram ID</label>
          <input type="number" id="telegram_id" name="telegram_id" value={formData.telegram_id} onChange={handleChange} placeholder="123456789 (empty = no access)" />
        </div>
        <div className="input-group">
          <label htmlFor="username_prefix">Username Prefix</label>
          <input type="text" id="username_prefix" name="username_prefix" value={formData.username_prefix} onChange={handleChange} placeholder="420 (auto-generates 4201, 4202...)" />
        </div>
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          <LoadingButton type="submit" className="btn" isLoading={isLoading}>{t('createAdminButton')}</LoadingButton>
        </div>
        {error && <p className="error-message">{error}</p>}
      </form>
    </Modal>
  );
};

export default AddAdminModal;