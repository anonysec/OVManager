import { useState } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

const AddAdminModal = ({ isOpen, onClose, onAdminCreated }) => {
  const { t } = useTranslation();
  const [formData, setFormData] = useState({ username: '', password: '' });
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
      const response = await apiClient.post('/admin/', formData);
      if (response.data.success) {
        onAdminCreated();
      } else {
        setError(response.data.msg || t('unableToCreateAdmin'));
      }
    } catch (err) {
      setError(err.response?.data?.detail || t('errorCreatingAdmin'));
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