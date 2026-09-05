// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import apiClient from '../../services/api';
import LoadingButton from '../../components/LoadingButton';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiSend, FiCheck } from 'react-icons/fi';
import { Card, Field } from './shared';

/* ═══════════════════════════════════════════════════════
   BOT — Telegram bot configuration (compact)
═══════════════════════════════════════════════════════ */
const BotSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [token, setToken] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [ownerId, setOwnerId] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [encryptKeyMissing, setEncryptKeyMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const r = await apiClient.get('/server/settings');
      const d = r.data?.data || {};
      setEnabled(d.bot_enabled || false);
      setOwnerId(d.owner_telegram_id || '');
      setEncryptKeyMissing(false);
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        bot_enabled: enabled,
        owner_telegram_id: ownerId ? Number(ownerId) : null,
        ...(token ? { bot_token: token } : {}),
      };
      const r = await apiClient.put('/server/settings/bot', payload);
      if (r.data?.success === false) {
        const msg = r.data?.msg || '';
        if (msg.toLowerCase().includes('encrypt')) setEncryptKeyMissing(true);
        addToast(msg || t('error', 'Error'), 'error');
      } else {
        addToast(t('saved', 'Bot settings saved.'), 'success');
        setToken(''); // token is write-only
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.response?.data?.msg || t('error', 'Error');
      if (msg.toLowerCase().includes('encrypt')) setEncryptKeyMissing(true);
      addToast(msg, 'error');
    } finally { setSaving(false); }
  };

  const clearToken = async () => {
    setSaving(true);
    try {
      await apiClient.put('/server/settings/bot', { bot_token: null, bot_enabled: false });
      setEnabled(false); setToken('');
      addToast(t('tokenCleared', 'Bot token cleared.'), 'success');
    } catch (e) { addToast(e.response?.data?.detail || t('error', 'Error'), 'error'); }
    finally { setSaving(false); }
  };

  if (loading) return <PanelSkeleton lines={3} label="Loading…" />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      <Card title={t('telegramBot', 'Telegram Bot')} icon={FiSend}>
        {encryptKeyMissing && (
          <div className="settings-alert settings-alert--error sp-mb-16" role="alert">
            <strong>{t('botEncryptKeyMissing', 'BOT_ENCRYPT_KEY not set')}</strong>
            <p>{t('botEncryptKeyMissingDesc', 'Set BOT_ENCRYPT_KEY in your .env before saving a token.')}</p>
          </div>
        )}

        <Field label={t('botToken', 'Bot Token')} hint={t('botDesc', 'From @BotFather. Operators use the menu and typed search — /start is the only command. Leave blank to keep the current token.')} inputId="bot-token">
          <input id="bot-token" className="sp-input" type="text" value={token} onChange={e => setToken(e.target.value)}
            placeholder="123456789:ABC…" disabled={encryptKeyMissing} />
        </Field>

        <Field label={t('ownerTelegramId', 'Owner Telegram ID')} hint={t('ownerTelegramIdHint', 'Your numeric Telegram user ID. After saving, open the bot and tap Start.')} inputId="bot-owner-id">
          <input id="bot-owner-id" className="sp-input" type="number" value={ownerId} onChange={e => setOwnerId(e.target.value)} placeholder="123456789" />
        </Field>

        <Field label={t('botEnabled', 'Enable Bot')} horizontal>
          <label className="sp-toggle">
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} disabled={encryptKeyMissing} aria-label={t('botEnabled', 'Enable Bot')} />
            <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
          </label>
        </Field>

        <div className="sp-btn-group sp-mt-20">
          <LoadingButton className="btn btn-sm" isLoading={saving} onClick={save} disabled={encryptKeyMissing}>
            {t('save', 'Save settings')}
          </LoadingButton>
          <button className="btn btn-sm btn-secondary" onClick={clearToken} disabled={saving}>
            {t('clearToken', 'Clear token')}
          </button>
        </div>
      </Card>
    </div>
  );
};

export default BotSection;
