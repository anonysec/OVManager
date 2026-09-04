import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from './LoadingButton';
import Modal from './Modal';

// Unified add/edit admin form. mode="create" (admin=null) or mode="edit".
// Replaces AddAdminModal + EditAdminModal, which were identical except for
// title/endpoint and username-disabled + password-required in edit.
const AdminFormModal = ({ admin, isOpen, onClose, onSaved }) => {
  const isEdit = !!admin;
  const { t } = useTranslation();
  const empty = { username: '', password: '', telegram_id: '', username_prefix: '' };
  const [formData, setFormData] = useState(empty);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (isEdit && admin) {
      setFormData({
        username: admin.username,
        password: '',
        telegram_id: admin.telegram_id != null ? String(admin.telegram_id) : '',
        username_prefix: admin.username_prefix || '',
      });
    } else if (!isEdit) {
      setFormData(empty);
    }
    setError('');
  }, [admin, isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    if (!formData.username || !formData.password) {
      setError(isEdit ? t('passwordRequired') : t('fillAllFields'));
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
      const response = isEdit
        ? await apiClient.put('/admin/', payload)
        : await apiClient.post('/admin/', payload);
      if (response.data.success) {
        onSaved();
      } else {
        setError(response.data.msg || (isEdit ? t('unableToUpdateAdmin') : t('unableToCreateAdmin')));
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map(d => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setError(JSON.stringify(detail));
      } else {
        setError(detail || (isEdit ? t('errorUpdatingAdmin') : t('errorCreatingAdmin')));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={isEdit ? t('editAdmin') : t('addNewAdmin')} size="small">
      <form onSubmit={handleSubmit} className="modal-form">
        <div className="input-group">
          <label htmlFor="admin-username">{t('username')}</label>
          {isEdit
            ? <input type="text" id="admin-username" name="username" value={formData.username} disabled readOnly />
            : <input type="text" id="admin-username" name="username" value={formData.username} onChange={handleChange} required />}
        </div>
        <div className="input-group">
          <label htmlFor="admin-password">{isEdit ? t('newPassword') : t('password')}</label>
          <input
            type="password" id="admin-password" name="password" value={formData.password} onChange={handleChange} required
            placeholder={isEdit ? t('enterNewPassword') : undefined}
          />
        </div>
        <div className="input-group">
          <label htmlFor="admin-telegram_id">{t("telegramId", "Telegram ID")}</label>
          <input type="number" id="admin-telegram_id" name="telegram_id" value={formData.telegram_id} onChange={handleChange} placeholder={t("telegramIdPlaceholder", "123456789 (empty = no access)")} />
        </div>
        <div className="input-group">
          <label htmlFor="admin-username_prefix">{t("usernamePrefix", "Username Prefix")}</label>
          <input type="text" id="admin-username_prefix" name="username_prefix" value={formData.username_prefix} onChange={handleChange} placeholder={t("usernamePrefixPlaceholder", "420 (auto-generates 4201, 4202...)")} />
        </div>
        <div className="modal-footer">
          <button type="button" onClick={onClose} className="btn btn-secondary">{t('cancelButton')}</button>
          <LoadingButton type="submit" className="btn" isLoading={isLoading}>
            {isEdit ? t('updateAdminButton') : t('createAdminButton')}
          </LoadingButton>
        </div>
        {error && <p className="error-message">{error}</p>}
      </form>
    </Modal>
  );
};

export default AdminFormModal;
