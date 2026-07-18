import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

const EditAdminModal = ({ admin, isOpen, onClose, onAdminUpdated }) => {
  const { t } = useTranslation();
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (admin) setFormData({ username: admin.username, password: '' });
  }, [admin]);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    if (!formData.password) {
      setError(t('passwordRequired'));
      return;
    }
    setIsLoading(true);
    try {
      const response = await apiClient.put('/admin/', formData);
      if (response.data.success) {
        onAdminUpdated();
      } else {
        setError(response.data.msg || t('unableToUpdateAdmin'));
      }
    } catch (err) {
      setError(err.response?.data?.detail || t('errorUpdatingAdmin'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('editAdmin')} size="small">
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="input-group">
          <label htmlFor="username">{t('username')}</label>
          <input type="text" id="username" name="username" value={formData.username} disabled readOnly />
        </div>
        <div className="input-group">
          <label htmlFor="password">{t('newPassword')}</label>
          <input type="password" id="password" name="password" value={formData.password} onChange={handleChange} required placeholder={t('enterNewPassword')} />
        </div>
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          <LoadingButton type="submit" className="btn" isLoading={isLoading}>{t('updateAdminButton')}</LoadingButton>
        </div>
        {error && <p className="error-message">{error}</p>}
      </form>
    </Modal>
  );
};

export default EditAdminModal;