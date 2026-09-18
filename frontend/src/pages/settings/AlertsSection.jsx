// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { readPrefs, writePref, REFRESH_OPTIONS } from '../../utils/notifPrefs';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';
import { FiBell, FiRefreshCw, FiAlertTriangle, FiSend } from 'react-icons/fi';
import { Card, Field } from './shared';

/* ═══════════════════════════════════════════════════════
   ALERTS & DASHBOARD — which alerts to surface + refresh
   Local prefs live in localStorage; the Telegram toggles
   are server-side flags on the Settings row.
═══════════════════════════════════════════════════════ */
const AlertsSection = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [prefs, setPrefs] = useState(readPrefs);
  const [telegram, setTelegram] = useState({ notify_expiry: true, notify_traffic: true, notify_node_down: true });
  const [telegramReady, setTelegramReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient.get('/server/settings')
      .then((res) => {
        if (cancelled) return;
        const data = res?.data?.data || {};
        // Default to ON when the fields are absent (older backend build).
        setTelegram({
          notify_expiry: data.notify_expiry !== false,
          notify_traffic: data.notify_traffic !== false,
          notify_node_down: data.notify_node_down !== false,
        });
      })
      .catch(() => { /* leave the defaults; the toggle still renders */ })
      .finally(() => { if (!cancelled) setTelegramReady(true); });
    return () => { cancelled = true; };
  }, []);

  const toggle = (key, value) => {
    writePref(key, value);
    setPrefs(readPrefs());
  };

  const toggleTelegram = async (key, value) => {
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
      </Card>

      <Card title={t('refreshCard', 'Refresh Interval')} icon={FiRefreshCw}>
        <Field label={t('refreshInterval', 'Dashboard refresh (seconds)')} hint={t('refreshDesc', 'How often the dashboard and notification bell poll for fresh data.')} inputId="alerts-refresh">
          <select id="alerts-refresh" className="sp-select" value={prefs.refreshSec} onChange={(e) => toggle('refreshSec', Number(e.target.value))}>
            {REFRESH_OPTIONS.map((sec) => (
              <option key={sec} value={sec}>{sec} {t('secondsUnit', 's')}</option>
            ))}
          </select>
        </Field>
      </Card>
    </div>
  );
};

export default AlertsSection;
