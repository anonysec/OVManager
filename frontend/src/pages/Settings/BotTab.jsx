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
  const [msgType, setMsgType] = useState('success'); // 'success' | 'error'
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [encryptKeyMissing, setEncryptKeyMissing] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const r = await apiClient.get('/server/settings');
      const d = r.data?.data || {};
      setToken(d.bot_token || '');
      setEnabled(d.bot_enabled || false);
      setOwnerId(d.owner_telegram_id || '');
      // If bot_configured is false and bot_enabled is false, the encryption
      // key may not be set. We detect this on a failed save — reset flag here.
      setEncryptKeyMissing(false);
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
        bot_token: token || undefined,
        bot_enabled: enabled,
        owner_telegram_id: ownerId ? Number(ownerId) : null,
      };
      const r = await apiClient.put('/server/settings/bot', payload);
      if (r.data?.success === false) {
        const detail = r.data?.msg || t('error', 'Error');
        // Detect missing encryption key scenario
        if (detail.toLowerCase().includes('bot_encrypt_key') || detail.toLowerCase().includes('encrypt')) {
          setEncryptKeyMissing(true);
        }
        setMsg(detail);
        setMsgType('error');
      } else {
        setMsg(r.data?.msg || t('saved', 'Saved'));
        setMsgType('success');
        setEncryptKeyMissing(false);
      }
    } catch (e) {
      const detail = e.response?.data?.detail || e.response?.data?.msg || t('error', 'Error');
      if (detail.toLowerCase().includes('bot_encrypt_key') || detail.toLowerCase().includes('encrypt')) {
        setEncryptKeyMissing(true);
      }
      setMsg(detail);
      setMsgType('error');
    }
    setSaving(false);
  };

  const clearToken = async () => {
    setSaving(true);
    setMsg('');
    try {
      await apiClient.put('/server/settings/bot', { bot_token: null, bot_enabled: false });
      setToken('');
      setEnabled(false);
      setMsg(t('tokenCleared', 'Bot token cleared.'));
      setMsgType('success');
      setEncryptKeyMissing(false);
    } catch (e) {
      setMsg(e.response?.data?.detail || t('error', 'Error'));
      setMsgType('error');
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

          {encryptKeyMissing && (
            <div className="settings-alert settings-alert--error" role="alert">
              <strong>{t('botEncryptKeyMissing', 'Encryption key not configured')}</strong>
              <p style={{ marginTop: 4, fontSize: '0.875rem' }}>
                {t('botEncryptKeyMissingDesc',
                  'BOT_ENCRYPT_KEY is not set in your .env file. Bot tokens cannot be saved without it. ' +
                  'Generate one with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )}
              </p>
            </div>
          )}

          <div className="input-group">
            <label htmlFor="bot-token">{t('botToken', 'Bot Token')}</label>
            <input
              id="bot-token"
              type="text"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="123456789:ABCdefGHI..."
              disabled={encryptKeyMissing}
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
              disabled={encryptKeyMissing}
            />
          </div>

          <button className="btn btn-mt-16" onClick={save} disabled={saving || encryptKeyMissing}>
            {saving ? t('saving', 'Saving...') : t('save', 'Save')}
          </button>

          <button
            className="btn btn-mt-8"
            onClick={clearToken}
            disabled={saving}
            style={{ marginLeft: 8 }}
          >
            {t('clearToken', 'Clear token')}
          </button>

          {msg && (
            <p className={`msg-accent${msgType === 'error' ? ' msg-accent--error' : ''}`}>
              {msg}
            </p>
          )}
        </>
      )}
    </div>
  );
};

export default BotTab;
