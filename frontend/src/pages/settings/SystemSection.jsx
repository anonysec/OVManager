// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { useLive } from '../../context/LiveContext';
import apiClient from '../../services/api';
import { settle } from '../../hooks/useAsyncData';
import LoadingButton from '../../components/LoadingButton';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiServer, FiZap, FiRefreshCw, FiBarChart2 } from 'react-icons/fi';
import { Card, Stat } from './shared';
import { formatBytes } from '../../utils/format';
import { formatUptime } from '../../utils/time';

/* ═══════════════════════════════════════════════════════
   SYSTEM (advanced) — Server info + maintenance actions
═══════════════════════════════════════════════════════ */
const SystemSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [sysInfo, setSysInfo] = useState(null);
  const [trafficTotal, setTrafficTotal] = useState(null);
  const [activeConns, setActiveConns] = useState(0);
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      // Independent: missing traffic history should not blank out server info.
      const res = await settle({
        info: apiClient.get('/server/info'),
        metrics: apiClient.get('/metrics/history?hours=24'),
      });
      if (res.info.ok) setSysInfo(res.info.data.data?.data || null);
      else setLoadError(true);
      const traffic = res.metrics.ok ? (res.metrics.data.data?.data?.traffic || []) : [];
      if (traffic.length) {
        setTrafficTotal(traffic.reduce((s, h) => s + Number(h.total_used || 0), 0));
        setActiveConns(traffic[traffic.length - 1]?.active_connections || 0);
      }
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const run = async (url, label) => {
    setBusy(url);
    try {
      await apiClient.post(url);
      addToast(label + ' ' + t('saved', 'done.'), 'success');
    } catch { addToast(t('error', 'Failed'), 'error'); }
    finally { setBusy(''); }
  };

  const spin = <span className="button-spinner" aria-hidden="true" />;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;
  if (loadError && !sysInfo) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      {sysInfo && (
        <Card title={t('serverInfo', 'Server Info')} icon={FiServer}>
          <div className="sp-stats-grid">
            <Stat label={t('kv_uptime', 'Uptime')} value={formatUptime(sysInfo.uptime)} />
            <Stat label={t('kv_cpu', 'CPU')} value={`${Number(sysInfo.cpu || 0).toFixed(0)}%`} tone={sysInfo.cpu > 85 ? 'danger' : sysInfo.cpu > 70 ? 'warn' : null} />
            <Stat label={t('kv_memory', 'Memory')} value={`${Number(sysInfo.memory_percent || 0).toFixed(0)}%`} tone={sysInfo.memory_percent > 85 ? 'danger' : sysInfo.memory_percent > 70 ? 'warn' : null} />
            <Stat label={t('kv_disk', 'Disk')} value={`${Number(sysInfo.disk_percent || 0).toFixed(0)}%`} tone={sysInfo.disk_percent > 85 ? 'danger' : null} />
            {trafficTotal != null && <Stat label={t('totalTraffic', 'Traffic 24h')} value={formatBytes(trafficTotal)} />}
            <Stat label={t('activeConnections', 'Active Conns')} value={activeConns} />
          </div>
        </Card>
      )}
      <Card title={t('maintenanceCard', 'Maintenance')} icon={FiZap}>
        <p className="sp-hint sp-mb-12">{t('maintenanceDesc', 'Run background jobs on demand. These also run automatically on a schedule.')}</p>
        <div className="sp-btn-group">
          <button className="btn btn-sm" disabled={!!busy} aria-busy={busy === '/metrics/collect'} onClick={() => run('/metrics/collect', t('collectNow', 'Metrics'))}>
            {busy === '/metrics/collect' ? spin : <><FiZap size={13} aria-hidden="true" /> {t('collectNow', 'Collect metrics')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/sync-limits'} onClick={() => run('/maintenance/sync-limits', t('syncLimits', 'Limits'))}>
            {busy === '/maintenance/sync-limits' ? spin : <><FiRefreshCw size={13} aria-hidden="true" /> {t('syncLimits', 'Sync limits')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/clean-stale'} onClick={() => run('/maintenance/clean-stale', t('cleanStale', 'Stale'))}>
            {busy === '/maintenance/clean-stale' ? spin : <><FiRefreshCw size={13} aria-hidden="true" /> {t('cleanStale', 'Clean stale sessions')}</>}
          </button>
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/clean-global-registry'} onClick={() => run('/maintenance/clean-global-registry', t('cleanRegistry', 'Registry'))}>
            {busy === '/maintenance/clean-global-registry' ? spin : <><FiBarChart2 size={13} aria-hidden="true" /> {t('cleanRegistry', 'Clean registry')}</>}
          </button>
        </div>
      </Card>
    </div>
  );
};

export default SystemSection;
