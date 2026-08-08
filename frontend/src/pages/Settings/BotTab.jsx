import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import ErrorState from '../../components/ui/ErrorState';

const BotTab = () => {
  const { t } = useTranslation();
  const [token, setToken] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [ownerId, setOwnerId] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadSettings = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const r = await apiClient.get('/server/settings');
      const d = r.data?.data || {};
      setToken(d.bot_token || '');
      setEnabled(d.bot_enabled || false);
      setOwnerId(d.owner_telegram_id || '');
    } catch {
      setError(t('failedToLoad', 'Failed to load data'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { loadSettings(); }, [loadSettings]);

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

  if (error) {
    return (
      <div className="settings-section">
        <ErrorState
          title={t('error', 'Error')}
          message={error}
          onRetry={loadSettings}
        />
      </div>
    );
  }

  return (
    <div className="settings-section">
      {!loading && (
        <>
          <h3>{t('telegramBot', 'Telegram Bot')}</h3>
          <p className="section-desc">
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

          <button className="btn btn-mt-16" onClick={save} disabled={saving}>
            {saving ? t('saving', 'Saving...') : t('save', 'Save')}
          </button>

          <button
            className="btn btn-mt-8"
            onClick={() => { setToken(''); save(); }}
            disabled={saving}
            style={{ opacity: token ? 1 : 0.5 }}
          >
            Clear token
          </button>

          {msg && <p className="msg-accent">{msg}</p>}
        </>
      )}
    </div>
  );
};

export default BotTab;