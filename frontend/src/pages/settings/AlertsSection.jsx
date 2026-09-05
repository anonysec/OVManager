// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { readPrefs, writePref, REFRESH_OPTIONS } from '../../utils/notifPrefs';
import { FiBell, FiRefreshCw, FiAlertTriangle } from 'react-icons/fi';
import { Card, Field } from './shared';

/* ═══════════════════════════════════════════════════════
   ALERTS & DASHBOARD — which alerts to surface + refresh
═══════════════════════════════════════════════════════ */
const AlertsSection = () => {
  const { t } = useTranslation();
  const [prefs, setPrefs] = useState(readPrefs);

  const toggle = (key, value) => {
    writePref(key, value);
    setPrefs(readPrefs());
  };

  const ALERTS = [
    { key: 'nodeDown', label: t('alertNodeDown', 'Node offline / unreachable'), icon: FiAlertTriangle },
    { key: 'maxLogins', label: t('alertMaxLogins', 'User at max logins'), icon: FiAlertTriangle },
    { key: 'authErrors', label: t('alertAuthErrors', 'Authentication errors'), icon: FiAlertTriangle },
    { key: 'rejects', label: t('alertRejects', 'Connection rejects'), icon: FiAlertTriangle },
    { key: 'stale', label: t('alertStale', 'Stale session markers'), icon: FiAlertTriangle },
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
