import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import Modal from './Modal';
import Button from './ui/Button';
import Field from './ui/Field';

const AdminFormModal = ({ admin, isOpen, onClose, onSaved, isOwner }: { admin?: any; isOpen?: any; onClose?: any; onSaved?: any; isOwner?: boolean }) => {
  const isEdit = !!admin;
  const { t } = useTranslation();
  const empty: any = { username: '', password: '', telegram_id: '', username_prefix: '' };
  const [formData, setFormData] = useState<any>(empty);
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

  const handleChange = (event: any) => {
    const { name, value } = event.target;
    setFormData((prev: any) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (event: any) => {
    event.preventDefault();
    setError('');
    if (!String(formData.username || '').trim()) {
      setError(t('fillAllFields'));
      return;
    }
    if (!isEdit && !formData.password) {
      setError(t('fillAllFields'));
      return;
    }
    setIsLoading(true);
    try {
      const payload: any = {
        username: formData.username,
        telegram_id: formData.telegram_id ? parseInt(formData.telegram_id, 10) : null,
        username_prefix: formData.username_prefix || null,
      };
      if (formData.password) payload.password = formData.password;
      if (isEdit && admin?.username) {
        payload.current_username = admin.username;
      }
      const response = isEdit
        ? await apiClient.put('/admin/', payload)
        : await apiClient.post('/admin/', payload);
      if (response.data.success) {
        onSaved(response.data.msg);
      } else {
        setError(response.data.msg || (isEdit ? t('unableToUpdateAdmin') : t('unableToCreateAdmin')));
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((d: any) => d.msg || JSON.stringify(d)).join(', '));
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
    <Modal isOpen={isOpen} onClose={onClose} title={isEdit ? `${t('editAdmin')} — ${admin?.username || ''}` : t('addNewAdmin')} size="medium">
      <form onSubmit={handleSubmit} className="modal-form">
        <Field label={t('username')} required hint={isOwner ? t('ownerUsernameHint', 'Renaming the owner cascades to its users and logs you out.') : undefined}>
          <input type="text" id="admin-username" name="username" value={formData.username} onChange={handleChange} required />
        </Field>
        <Field
          label={isEdit ? t('newPassword') : t('password')}
          hint={isEdit ? t('nodeKeepCurrentHint', 'Leave empty to keep the current value.') : t('minPasswordHint', 'Minimum 8 characters')}
          required={!isEdit}
        >
          <input
            type="password" id="admin-password" name="password" value={formData.password} onChange={handleChange}
            minLength={isEdit ? undefined : 8} autoComplete={isEdit ? 'new-password' : undefined}
          />
        </Field>
        <Field label={t('telegramId', 'Telegram ID')} hint={t('adminTelegramHint', 'Numeric Telegram user ID. Empty = no bot access.')}>
          <input type="number" id="admin-telegram_id" name="telegram_id" value={formData.telegram_id} onChange={handleChange} placeholder="123456789" />
        </Field>
        <Field label={t('usernamePrefix', 'Username Prefix')} hint={t('adminPrefixHint', 'Auto-generates user names such as 4201, 4202…')}>
          <input type="text" id="admin-username_prefix" name="username_prefix" value={formData.username_prefix} onChange={handleChange} placeholder="420" />
        </Field>
        {error && <p className="modal-error" role="alert">{error}</p>}
        <div className="modal-footer">
          <Button variant="secondary" onClick={onClose}>{t('cancelButton')}</Button>
          <Button type="submit" variant="primary" loading={isLoading}>
            {isEdit ? t('updateAdminButton') : t('createAdminButton')}
          </Button>
        </div>
      </form>
    </Modal>
  );
};

export default AdminFormModal;
