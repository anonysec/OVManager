// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { readPrefs, writePref } from '../../utils/notifPrefs';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';
import LoadingButton from '../../components/LoadingButton';
import { FiBell, FiAlertTriangle, FiSend } from 'react-icons/fi';
import { Card } from './shared';

/* ═══════════════════════════════════════════════════════
   ALERTS & DASHBOARD — which alerts to surface + refresh
   Local prefs live in localStorage; the Telegram toggles
   and the D2 thresholds are server-side flags on the
   Settings row.
═══════════════════════════════════════════════════════ */

type Thresholds = { alert_days_left: string; alert_usage_pct: string; alert_cpu_pct: string };

const DEFAULT_THRESHOLDS: Thresholds = { alert_days_left: '3', alert_usage_pct: '80', alert_cpu_pct: '85' };

const apiMsg = (e: any, fallback: string) =>
  e?.response?.data?.msg || e?.response?.data?.detail || e?.message || fallback;

const AlertsSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [prefs, setPrefs] = useState<Record<string, boolean>>(readPrefs);
  const [telegram, setTelegram] = useState<Record<string, boolean>>({
    notify_expiry: true,
    notify_traffic: true,
    notify_node_down: true,
    alert_usage_enabled: true,
    alert_cpu_enabled: true,
  });
  const [thresholds, setThresholds] = useState<Thresholds>(DEFAULT_THRESHOLDS);
  const [telegramReady, setTelegramReady] = useState(false);
  const [savingThresholds, setSavingThresholds] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient.get('/server/settings')
      .then((res) => {
        if (cancelled) return;
        const data = res?.data?.data || {};
        setTelegram({
          notify_expiry: data.notify_expiry !== false,
          notify_traffic: data.notify_traffic !== false,
          notify_node_down: data.notify_node_down !== false,
          alert_usage_enabled: data.alert_usage_enabled !== false,
          alert_cpu_enabled: data.alert_cpu_enabled !== false,
        });
        setThresholds({
          alert_days_left: String(data.alert_days_left ?? 3),
          alert_usage_pct: String(data.alert_usage_pct ?? 80),
          alert_cpu_pct: String(data.alert_cpu_pct ?? 85),
        });
      })
      .catch(() => { /* leave the defaults; the toggle still renders */ })
      .finally(() => { if (!cancelled) setTelegramReady(true); });
    return () => { cancelled = true; };
  }, []);

  const toggle = (key: string, value: boolean) => {
    writePref(key, value);
    setPrefs(readPrefs());
  };

  const toggleTelegram = async (key: string, value: boolean) => {
    const previous = telegram;
    setTelegram((current) => ({ ...current, [key]: value }));
    try {
      const res = await apiClient.put('/server/settings/bot', { [key]: value });
      if (res?.data?.success === false) throw new Error(res.data.msg || 'save failed');
    } catch {
      setTelegram(previous);
      addToast(t('error', 'Failed'), 'error');
    }
  };

  const setThreshold = (key: keyof Thresholds, value: string) => {
    setThresholds((current) => ({ ...current, [key]: value }));
  };

  const saveThresholds = async () => {
    const payload = {
      alert_days_left: Number(thresholds.alert_days_left),
      alert_usage_pct: Number(thresholds.alert_usage_pct),
      alert_cpu_pct: Number(thresholds.alert_cpu_pct),
    };
    if (Object.values(payload).some((v) => !Number.isFinite(v))) {
      addToast(t('thresholdsInvalid', 'Thresholds must be numbers'), 'error');
      return;
    }
    setSavingThresholds(true);
    try {
      const res = await apiClient.put('/server/settings/bot', payload);
      if (res?.data?.success === false) throw new Error(res.data.msg || 'save failed');
      addToast(t('saved', 'Saved.'), 'success');
    } catch (e) {
      addToast(apiMsg(e, t('error', 'Error')), 'error');
    } finally {
      setSavingThresholds(false);
    }
  };

  const sendTest = async () => {
    setTesting(true);
    try {
      const res = await apiClient.post('/server/alerts/test', { channel: 'telegram' });
      if (res?.data?.success === false) throw new Error(res.data.msg || 'test failed');
      addToast(t('alertTestSent', 'Test alert sent to Telegram.'), 'success');
    } catch (e) {
      addToast(apiMsg(e, t('error', 'Error')), 'error');
    } finally {
      setTesting(false);
    }
  };

  const ALERTS = [
    { key: 'nodeDown', label: t('alertNodeDown', 'Node offline / unreachable'), icon: FiAlertTriangle },
    { key: 'maxLogins', label: t('alertMaxLogins', 'User at max logins'), icon: FiAlertTriangle },
    { key: 'authErrors', label: t('alertAuthErrors', 'Authentication errors'), icon: FiAlertTriangle },
    { key: 'rejects', label: t('alertRejects', 'Connection rejects'), icon: FiAlertTriangle },
    { key: 'quota', label: t('alertQuota', 'Quota warnings (80%+)'), icon: FiAlertTriangle },
  ];

  const TELEGRAM_ALERTS = [
    { key: 'notify_expiry', label: t('notifyExpiry', 'Users expiring within 3 days') },
    { key: 'notify_traffic', label: t('notifyTraffic', 'Users out of traffic') },
    { key: 'notify_node_down', label: t('notifyNodeDown', 'Node goes down or comes back') },
    { key: 'alert_usage_enabled', label: t('alertUsageToggle', 'Quota usage % warnings') },
    { key: 'alert_cpu_enabled', label: t('alertCpuToggle', 'Node CPU % warnings') },
  ];

  const THRESHOLDS: Array<{ key: keyof Thresholds; label: string; min: number; max: number }> = [
    { key: 'alert_days_left', label: t('thresholdDaysLeft', 'Warn {{n}} days before a user expires', { n: thresholds.alert_days_left }), min: 0, max: 365 },
    { key: 'alert_usage_pct', label: t('thresholdUsagePct', "Warn at {{n}}% of a user's quota", { n: thresholds.alert_usage_pct }), min: 1, max: 100 },
    { key: 'alert_cpu_pct', label: t('thresholdCpuPct', 'Warn at {{n}}% node CPU', { n: thresholds.alert_cpu_pct }), min: 1, max: 100 },
  ];

  return (
    <div className="sp-cards">
      <Card title={t('alertsCard', 'Alert Types')} icon={FiBell}>
        <p className="sp-hint sp-mb-12">{t('alertsDesc', 'Choose which alerts appear in the topbar bell and the dashboard strip.')}</p>
        <div className="sp-alert-list">
          {ALERTS.map((item) => (
            <label key={item.key} className="sp-alert-row">
              <span className="sp-alert-label"><item.icon size={13} aria-hidden="true" /> {item.label}</span>
              <span className="sp-toggle">
                <input type="checkbox" checked={prefs[item.key] !== false} onChange={(e) => toggle(item.key, e.target.checked)} />
                <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card title={t('notifyTelegramCard', 'Telegram alerts')} icon={FiSend}>
        <p className="sp-hint sp-mb-12">{t('notifyTelegramDesc', 'One daily Telegram summary of users expiring soon or out of traffic, plus an instant alert when a node goes down or comes back. Uses the bot token and owner ID from the Bot section.')}</p>
        <div className="sp-alert-list">
          {TELEGRAM_ALERTS.map((item) => (
            <label key={item.key} className="sp-alert-row">
              <span className="sp-alert-label">{item.label}</span>
              <span className="sp-toggle">
                <input
                  type="checkbox"
                  checked={telegram[item.key] !== false}
                  disabled={!telegramReady}
                  onChange={(e) => toggleTelegram(item.key, e.target.checked)}
                />
                <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
              </span>
            </label>
          ))}
        </div>
        <div className="sp-btn-group sp-mt-20">
          <LoadingButton className="btn btn-sm btn-secondary" isLoading={testing} onClick={sendTest} disabled={!telegramReady}>
            {t('sendTestAlert', 'Send test alert')}
          </LoadingButton>
        </div>
      </Card>

      <Card title={t('thresholdsCard', 'Thresholds')} icon={FiAlertTriangle}>
        <p className="sp-hint sp-mb-12">{t('thresholdsDesc', 'One Telegram alert when a threshold first trips; silent while the condition persists.')}</p>
        <div className="sp-alert-list">
          {THRESHOLDS.map((item) => (
            <label key={item.key} className="sp-alert-row" htmlFor={`th-${item.key}`}>
              <span className="sp-alert-label">{item.label}</span>
              <input
                id={`th-${item.key}`}
                className="sp-input"
                type="number"
                min={item.min}
                max={item.max}
                value={thresholds[item.key]}
                disabled={!telegramReady}
                onChange={(e) => setThreshold(item.key, e.target.value)}
                style={{ width: 90, flex: '0 0 auto' }}
              />
            </label>
          ))}
        </div>
        <div className="sp-btn-group sp-mt-20">
          <LoadingButton className="btn btn-sm" isLoading={savingThresholds} onClick={saveThresholds} disabled={!telegramReady}>
            {t('save', 'Save')}
          </LoadingButton>
        </div>
      </Card>
    </div>
  );
};

export default AlertsSection;
