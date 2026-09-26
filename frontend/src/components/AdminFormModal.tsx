import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import Modal from './Modal';
import Button from './ui/Button';
import Field from './ui/Field';

// Unified add/edit admin form. mode="create" (admin=null) or mode="edit".
// Replaces AddAdminModal + EditAdminModal, which were identical except for
// title/endpoint and username-disabled + password-required in edit.
const AdminFormModal = ({ admin, isOpen, onClose, onSaved }) => {
  const isEdit = !!admin;
  const { t } = useTranslation();
  const empty = { username: '', password: '', telegram_id: '', username_prefix: '', default_days: '', default_traffic_gb: '', default_max_users: '' };
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
        default_days: admin.default_days != null ? String(admin.default_days) : '',
        default_traffic_gb: admin.default_traffic_gb != null ? String(admin.default_traffic_gb) : '',
        default_max_users: admin.default_max_users != null ? String(admin.default_max_users) : '',
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

  const _intOrNull = (raw) => {
    if (raw === '' || raw == null) return null;
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : null;
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
        // null clears the override — the admin then inherits the owner global.
        default_days: _intOrNull(formData.default_days),
        default_traffic_gb: _intOrNull(formData.default_traffic_gb),
        default_max_users: _intOrNull(formData.default_max_users),
      };
      const response = isEdit
        ? await apiClient.put('/admin/', payload)
        : await apiClient.post('/admin/', payload);
      if (response.data.success) {
        // Hand the backend message to the caller so it can surface it in a toast.
        onSaved(response.data.msg);
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
    <Modal isOpen={isOpen} onClose={onClose} title={isEdit ? `${t('editAdmin')} — ${admin?.username || ''}` : t('addNewAdmin')} size="medium">
      <form onSubmit={handleSubmit} className="modal-form">
        <Field label={t('username')} required={!isEdit}>
          {isEdit
            ? <input type="text" id="admin-username" name="username" value={formData.username} disabled readOnly />
            : <input type="text" id="admin-username" name="username" value={formData.username} onChange={handleChange} required />}
        </Field>
        <Field
          label={isEdit ? t('newPassword') : t('password')}
          hint={t('minPasswordHint', 'Minimum 8 characters')}
          required
        >
          <input
            type="password" id="admin-password" name="password" value={formData.password} onChange={handleChange} required
            minLength={8} autoComplete={isEdit ? 'new-password' : undefined}
          />
        </Field>
        <Field label={t('telegramId', 'Telegram ID')} hint={t('adminTelegramHint', 'Numeric Telegram user ID. Empty = no bot access.')}>
          <input type="number" id="admin-telegram_id" name="telegram_id" value={formData.telegram_id} onChange={handleChange} placeholder="123456789" />
        </Field>
        <Field label={t('usernamePrefix', 'Username Prefix')} hint={t('adminPrefixHint', 'Auto-generates user names such as 4201, 4202…')}>
          <input type="text" id="admin-username_prefix" name="username_prefix" value={formData.username_prefix} onChange={handleChange} placeholder="420" />
        </Field>
        <p className="sp-hint sp-mb-6">
          {t('adminDefaultsHint', 'New user defaults for this admin. Leave empty to inherit the global defaults from Settings → Defaults.')}
        </p>
        <div className="sp-two-col">
          <Field label={t('defaultDays', 'Default expiry (days)')} inputId="admin-default-days">
            <input id="admin-default-days" name="default_days" className="sp-input" type="number" min={1} max={3650} value={formData.default_days} onChange={handleChange} />
          </Field>
          <Field label={t('defaultTrafficGb', 'Default traffic (GB)')} inputId="admin-default-traffic">
            <input id="admin-default-traffic" name="default_traffic_gb" className="sp-input" type="number" min={0} max={1000000} value={formData.default_traffic_gb} onChange={handleChange} />
          </Field>
        </div>
        <Field label={t('defaultDevices', 'Default devices per user')} hint={t('defaultDevicesHint', 'Simultaneous logins allowed for each new user. 0 = unlimited.')} inputId="admin-default-devices">
          <input id="admin-default-devices" name="default_max_users" className="sp-input" type="number" min={0} max={1000} value={formData.default_max_users} onChange={handleChange} />
        </Field>
        {isEdit && admin?.effective_defaults && (
          <p className="sp-hint sp-mt-6">
            {t('adminDefaultsEffective', 'Currently in effect: {{days}} days · {{traffic}} GB · {{devices}} devices', {
              days: admin.effective_defaults.days,
              traffic: admin.effective_defaults.traffic_gb,
              devices: admin.effective_defaults.max_users,
            })}
          </p>
        )}
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
