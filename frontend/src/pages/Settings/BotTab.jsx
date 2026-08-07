import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';

const BotTab = () => {
  const { t } = useTranslation();
  const [token, setToken] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [ownerId, setOwnerId] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    apiClient.get('/server/settings').then((r) => {
      const d = r.data?.data || {};
      setToken(d.bot_token || '');
      setEnabled(d.bot_enabled || false);
      setOwnerId(d.owner_telegram_id || '');
    }).catch(() => {});
  }, []);

  const save = async () => {
    setSaving(true);
    setMsg('');
    try {
      const payload = {
        bot_token: token,
        bot_enabled: enabled,
        owner_telegram_id: ownerId ? Number(ownerId) : null,
      };
      const r = await apiClient.put('/server/settings/bot', payload);
      setMsg(r.data?.msg || t('saved', 'Saved'));
    } catch (e) {
      setMsg(e.response?.data?.detail || t('error', 'Error'));
    }
    setSaving(false);
  };

  return (
    <div className="settings-section">
      <h3>{t('telegramBot', 'Telegram Bot')}</h3>
      <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 20 }}>
        {t('botDesc', 'Configure the Telegram bot for user management and notifications.')}
      </p>

      <div className="input-group">
        <label htmlFor="bot-token">{t('botToken', 'Bot Token')}</label>
        <input
          id="bot-token"
          type="text"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="123456789:ABCdefGHI..."
        />
      </div>

      <div className="input-group">
        <label htmlFor="bot-owner">{t('ownerTelegramId', 'Owner Telegram ID')}</label>
        <input
          id="bot-owner"
          type="number"
          value={ownerId}
          onChange={(e) => setOwnerId(e.target.value)}
          placeholder="123456789"
        />
      </div>

      <div className="input-group" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <label htmlFor="bot-enabled" style={{ marginBottom: 0 }}>{t('botEnabled', 'Enable Bot')}</label>
        <input
          id="bot-enabled"
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          style={{ width: 'auto' }}
        />
      </div>

      <button className="btn" onClick={save} disabled={saving} style={{ marginTop: 16 }}>
        {saving ? t('saving', 'Saving...') : t('save', 'Save')}
      </button>

      <button
        className="btn"
        onClick={() => { setToken(''); save(); }}
        disabled={saving}
        style={{ marginTop: 8, marginLeft: 8, opacity: token ? 1 : 0.5 }}
      >
        Clear token
      </button>

      {msg && <p style={{ marginTop: 12, color: 'var(--accent-color)', fontSize: 14 }}>{msg}</p>}
    </div>
  );
};

export default BotTab;
