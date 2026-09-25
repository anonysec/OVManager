// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useLive } from '../../context/LiveContext';
import apiClient from '../../services/api';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiShield } from 'react-icons/fi';
import { Card, Stat } from './shared';

const SEVERITY_RANK = { failure: 0, warn: 1, policy: 2 };

const reasonLabel = (t, ev) => {
  const known = {
    disabled: t('secReasonDisabled', 'User disabled'),
    max_logins: t('secReasonMaxLogins', 'Max devices reached'),
    global_policy: t('secReasonGlobalPolicy', 'Blocked by panel policy'),
    global_check: t('secReasonGlobalCheck', 'Panel check failed'),
    fail_closed: t('secReasonFailClosed', 'Node state missing'),
    takeover_failed: t('secReasonTakeover', 'Old session not closed'),
    mgmt_degraded: t('secReasonMgmt', 'Management unavailable'),
    tls: t('secReasonTls', 'TLS handshake failed'),
    tls_auth: t('secReasonTlsAuth', 'Certificate rejected'),
    other: t('secReasonOther', 'Unclassified reject'),
  };
  return known[ev.action] || ev.reason || t('secReasonOther', 'Unclassified reject');
};

const EventRow = ({ ev, t }) => {
  const when = ev.time_local || (ev.ts ? new Date(ev.ts * 1000).toLocaleString() : t('secTimeUnknown', 'time unknown'));
  const who = ev.user || ev.cn || ev.peer || '—';
  return (
    <div className={`sp-node-row sp-err-row sp-ev sp-ev--${ev.severity || 'warn'}`}>
      <span className="sp-node-name">{who}</span>
      <span className="sp-cell-sub">
        {[ev.node, when, ev.peer && ev.peer !== who ? ev.peer : ''].filter(Boolean).join(' · ')}
      </span>
      <span className="sp-ev-tags">
        {ev.ongoing && <span className="sp-badge sp-badge--ongoing">{t('secOngoing', 'ongoing')}</span>}
        <span className={`sp-badge${ev.severity === 'failure' ? ' danger' : ev.severity === 'warn' ? ' warn' : ''}`}>
          {reasonLabel(t, ev)}
        </span>
      </span>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════
   SECURITY — connection events, split by what they mean
   ═══════════════════════════════════════════════════════ */
const SecuritySection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const [hours, setHours] = useState(8);
  const [sec, setSec] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setLoading(true); setError(null); const r = await apiClient.get(`/security/summary?hours=${hours}`); setSec(r.data?.data || null); }
    catch { setError(t('failedToLoad', 'Failed to load')); } finally { setLoading(false); }
  }, [hours, t]);

  useEffect(() => { load(); }, [load, refreshTick]);

  const events = Array.isArray(sec?.events) ? sec.events : [];
  const danger = events.filter((e) => e.severity === 'failure');
  const rest = events.filter((e) => e.severity !== 'failure')
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3));
  const authFailures = sec?.auth_failures ?? sec?.auth_errors ?? 0;

  return (
    <div className="sp-cards">
      <Card title={t('securityCard', 'Connection Events')} icon={FiShield}>
        <div className="sp-hours-toggle" role="group" aria-label={t('securityWindow', 'Time window')}>
          {[4, 8, 12, 24, 48].map(h => (
            <button key={h} type="button" className={`sp-hour-btn${hours === h ? ' active' : ''}`} aria-pressed={hours === h} onClick={() => setHours(h)}>{h}h</button>
          ))}
        </div>
        {error && <ErrorState title={t('error', 'Error')} message={error} onRetry={load} />}
        {loading && !error && <PanelSkeleton lines={3} label="Loading…" />}
        {!loading && !error && sec && (
          <div className="sp-stats-grid">
            <Stat label={t('authFailures', 'Auth / TLS failures')} value={authFailures} tone={authFailures > 0 ? 'danger' : null} />
            <Stat label={t('policyRejects', 'Blocked by policy')} value={sec.policy_rejects || 0} tone={sec.policy_rejects > 0 ? 'warn' : null} />
            <Stat label={t('staleMarkers', 'Stale Markers')} value={sec.stale_markers || 0} tone={sec.stale_markers > 5 ? 'warn' : null} />
          </div>
        )}
        {!loading && !error && sec && authFailures === 0 && (
          <p className="sp-hint sp-mt-12">
            {t('secNoFailures', 'No authentication or TLS failures in this window. Blocked connections below are expected policy decisions (disabled user, device limit, panel rules).')}
          </p>
        )}
        {sec?.per_node?.length > 0 && (
          <div className="sp-mt-16">
            <p className="sp-label-xs sp-mb-6">{t('th_node', 'Per Node')}</p>
            <div className="sp-node-list">
              {sec.per_node.map(n => (
                <div key={n.node} className="sp-node-row">
                  <span className="sp-node-name">{n.node}</span>
                  <span className={`sp-badge${(n.auth_failures ?? n.auth_errors ?? 0) > 0 ? ' danger' : ''}`}>
                    {n.auth_failures ?? n.auth_errors ?? 0} {t('secFail', 'fail')}
                  </span>
                  <span className="sp-badge">{n.policy_rejects || 0} {t('secBlocked', 'blocked')}</span>
                  <span className="sp-badge">{n.live} {t('secLive', 'live')}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {(sec?.timezone || sec?.hours) && (
          <p className="sp-hint sp-mt-12">
            {t('securityWindow', 'Window: last {{hours}}h · {{timezone}}', { hours: sec.hours ?? hours, timezone: sec.timezone || 'UTC' })}
          </p>
        )}
        {Array.isArray(sec?.ongoing_users) && sec.ongoing_users.length > 0 && (
          <div className="sp-mt-12">
            <p className="sp-label-xs sp-mb-6">{t('secStillTrying', 'Still retrying (last hour)')}</p>
            <div className="sp-chip-row">
              {sec.ongoing_users.map((u) => <span key={u} className="sp-chip">{u}</span>)}
            </div>
          </div>
        )}
        {danger.length > 0 && (
          <div className="sp-mt-16">
            <p className="sp-label-xs sp-mb-6">{t('secDangerTitle', 'Authentication / TLS failures')}</p>
            <div className="sp-node-list">
              {danger.slice(0, 20).map((e, i) => <EventRow key={`${e.ts}-${e.cn}-${i}`} ev={e} t={t} />)}
            </div>
          </div>
        )}
        {rest.length > 0 && (
          <div className="sp-mt-16">
            <p className="sp-label-xs sp-mb-6">{t('secBlockedTitle', 'Blocked connections (expected)')}</p>
            <div className="sp-node-list">
              {rest.slice(0, 20).map((e, i) => <EventRow key={`${e.ts}-${e.cn}-${i}`} ev={e} t={t} />)}
            </div>
          </div>
        )}
        {!loading && !error && events.length === 0 && (
          <p className="sp-hint sp-mt-12">{t('secNoEvents', 'No connection events in this window.')}</p>
        )}
      </Card>
    </div>
  );
};

export default SecuritySection;
