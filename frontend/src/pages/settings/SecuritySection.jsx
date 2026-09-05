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

/* ═══════════════════════════════════════════════════════
   SECURITY (advanced) — Auth summary
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

  return (
    <div className="sp-cards">
      <Card title={t('securityCard', 'Authentication Summary')} icon={FiShield}>
        <div className="sp-hours-toggle" role="group" aria-label={t('securityWindow', 'Time window')}>
          {[4, 8, 12, 24, 48].map(h => (
            <button key={h} type="button" className={`sp-hour-btn${hours === h ? ' active' : ''}`} aria-pressed={hours === h} onClick={() => setHours(h)}>{h}h</button>
          ))}
        </div>
        {error && <ErrorState title={t('error', 'Error')} message={error} onRetry={load} />}
        {loading && !error && <PanelSkeleton lines={3} label="Loading…" />}
        {!loading && !error && sec && (
          <div className="sp-stats-grid">
            <Stat label={t('authErrors', 'Auth Errors')} value={sec.auth_errors || 0} tone={sec.auth_errors > 0 ? 'danger' : null} />
            <Stat label={t('rejects', 'Rejects')} value={sec.rejects || 0} tone={sec.rejects > 0 ? 'warn' : null} />
            <Stat label={t('staleMarkers', 'Stale Markers')} value={sec.stale_markers || 0} tone={sec.stale_markers > 5 ? 'warn' : null} />
          </div>
        )}
        {sec?.per_node?.length > 0 && (
          <div className="sp-mt-16">
            <p className="sp-label-xs sp-mb-6">{t('th_node', 'Per Node')}</p>
            <div className="sp-node-list">
              {sec.per_node.map(n => (
                <div key={n.node} className="sp-node-row">
                  <span className="sp-node-name">{n.node}</span>
                  <span className={`sp-badge${n.auth_errors > 0 ? ' danger' : ''}`}>{n.auth_errors} err</span>
                  <span className="sp-badge">{n.live} live</span>
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
        {Array.isArray(sec?.top_common_names) && sec.top_common_names.length > 0 && (
          <div className="sp-mt-12">
            <p className="sp-label-xs sp-mb-6">{t('topCommonNames', 'Most affected identities')}</p>
            <div className="sp-chip-row">
              {sec.top_common_names.slice(0, 10).map(([cn, count]) => (
                <span key={cn} className="sp-chip" title={`${count} events`}>{cn} · {count}</span>
              ))}
            </div>
          </div>
        )}
        {Array.isArray(sec?.last_errors) && sec.last_errors.length > 0 && (
          <div className="sp-mt-12">
            <p className="sp-label-xs sp-mb-6">{t('lastErrors', 'Latest auth events')}</p>
            <div className="sp-node-list">
              {sec.last_errors.slice(0, 5).map((e, i) => (
                <div key={`${e.ts}-${e.common_name}-${i}`} className="sp-node-row sp-err-row">
                  <span className="sp-node-name">{e.common_name || e.username || '—'}</span>
                  <span className="sp-cell-sub">{[e.node, e.time_local || (e.ts ? new Date(e.ts * 1000).toLocaleString() : '')].filter(Boolean).join(' · ')}</span>
                  <span className={`sp-badge${e.action === 'reject' ? ' danger' : ''}`}>{e.reason || e.action || 'event'}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
};

export default SecuritySection;
