// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import apiClient from '../../services/api';
import LoadingButton from '../../components/LoadingButton';
import { PanelSkeleton } from '../../components/ui';
import ErrorState from '../../components/ui/ErrorState';
import { FiSend, FiClock } from 'react-icons/fi';
import { Card, Field } from './shared';
import { errorMessageOf } from '../../utils/errorMessage';

/* ═══════════════════════════════════════════════════════
   TELEGRAM — ops notification channel (plan Task 4):
   daily usage summary, expired/over-quota events, node
   and CPU alerts. Same settings row as BotSection; this
   card adds the summary cadence and the send-test result.
════════════════════════════════════════════════════════ */
type SharedState = {
  loading?: boolean;
  error?: boolean;
  reload?: () => void;
  data?: any;
};

const TelegramSection = ({ shared }: { shared?: SharedState }) => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [enabled, setEnabled] = useState(false);
  const [token, setToken] = useState('');
  const [chatId, setChatId] = useState('');
  const [summaryTime, setSummaryTime] = useState('09:00');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState('');
  const loading = shared?.loading ?? true;
  const loadError = shared?.error ?? false;
  const load = shared?.reload ?? (() => {});
  const synced = useRef(false);

  useEffect(() => {
    const d = shared?.data;
    if (!d || synced.current) return;
    synced.current = true;
    setEnabled(d.bot_enabled || false);
    setChatId(d.owner_telegram_id != null ? String(d.owner_telegram_id) : '');
    // bot_token arrives masked (last 4 chars) as a placeholder, never the secret.
    setSummaryTime(d.telegram_summary_time || '09:00');
  }, [shared]);

  const save = async () => {
    if (chatId && !Number.isFinite(Number(chatId))) {
      addToast(t('invalidChatId', 'Chat ID must be a number.'), 'error');
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, any> = {
        bot_enabled: enabled,
        owner_telegram_id: chatId ? Number(chatId) : null,
        telegram_summary_time: summaryTime,
        ...(token ? { bot_token: token } : {}),
      };
      const r = await apiClient.put('/server/settings/bot', payload);
      if (r.data?.success === false) {
        addToast(r.data?.msg || t('error', 'Error'), 'error');
      } else {
        addToast(t('saved', 'Saved.'), 'success');
        setToken(''); // the token is write-only
        load();
      }
    } catch (e) {
      addToast(errorMessageOf(e, t('error', 'Error')), 'error');
    } finally { setSaving(false); }
  };

  const sendTest = async () => {
    setTesting(true);
    setTestResult('');
    try {
      const r = await apiClient.post('/server/alerts/test', { channel: 'telegram' });
      const ok = r.data?.success !== false;
      const msg = r.data?.msg || (ok ? t('telegramTestOk', 'Test message sent.') : t('telegramTestFail', 'Test failed'));
      setTestResult(msg);
      addToast(msg, ok ? 'success' : 'error');
    } catch (e) {
      const msg = errorMessageOf(e, t('telegramTestFail', 'Test failed'));
      setTestResult(msg);
      addToast(msg, 'error');
    } finally { setTesting(false); }
  };

  if (loading && !shared?.data) return <PanelSkeleton lines={3} label={t('loading', 'Loading…')} />;
  if (loadError) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      <Card title={t('settingsTelegram', 'Telegram notifications')} icon={FiSend}>
        <Field label={t('botEnabled', 'Enable Bot')} hint={t('telegramEnabledHint', 'Daily summary, expired/over-quota events and node/CPU alerts go to the owner chat.')} horizontal inputId="telegram-enabled">
          <label className="sp-toggle">
            <input id="telegram-enabled" type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} aria-label={t('botEnabled', 'Enable Bot')} />
            <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
          </label>
        </Field>

        <Field label={t('botToken', 'Bot Token')} hint={t('telegramTokenMasked', 'From @BotFather, write-only — the saved token shows as ••…last4.')} inputId="telegram-token">
          <input id="telegram-token" className="sp-input" type="password" value={token} onChange={e => setToken(e.target.value)}
            placeholder={shared?.data?.bot_token ? `••${shared.data.bot_token}` : '123456789:ABC…'} />
        </Field>

        <Field label={t('telegramChatId', 'Chat ID')} hint={t('ownerTelegramIdHint', 'Your numeric Telegram user ID. After saving, open the bot and tap Start.')} inputId="telegram-chat-id">
          <input id="telegram-chat-id" className="sp-input" type="number" value={chatId} onChange={e => setChatId(e.target.value)} placeholder="123456789" />
        </Field>

        <Field label={t('telegramSummaryTime', 'Daily summary time (HH:MM)')} hint={t('telegramSummaryHint', '24-hour time; the usage report is sent once a day at this time.')} inputId="telegram-summary-time">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <FiClock size={14} aria-hidden="true" />
            <input id="telegram-summary-time" className="sp-input" style={{ maxWidth: 120 }} type="time" value={summaryTime}
              onChange={e => setSummaryTime(e.target.value)} aria-label={t('telegramSummaryTime', 'Daily summary time')} />
          </div>
        </Field>

        <div className="sp-btn-group sp-mt-20">
          <LoadingButton className="btn btn-sm" isLoading={saving} onClick={save}>
            {t('save', 'Save settings')}
          </LoadingButton>
        </div>

        <div className="sp-btn-group sp-mt-20">
          <LoadingButton className="btn btn-sm btn-secondary" isLoading={testing} onClick={sendTest}>
            {t('telegramSendTest', 'Send test message')}
          </LoadingButton>
          {testResult && <p className="sp-hint sp-mt-12" role="status">{testResult}</p>}
        </div>
      </Card>
    </div >
  );
};

export default TelegramSection;
