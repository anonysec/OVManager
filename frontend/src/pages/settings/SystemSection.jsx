// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { useLive } from '../../context/LiveContext';
import { useAuth } from '../../context/AuthContext';
import apiClient from '../../services/api';
import { settle } from '../../hooks/useAsyncData';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import ErrorState from '../../components/ui/ErrorState';
import { FiServer, FiZap, FiRefreshCw, FiDownload } from 'react-icons/fi';
import { Card, Stat } from './shared';
import { formatBytes } from '../../utils/format';
import { formatUptime } from '../../utils/time';
import '../UpdateNotice.css';

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

const updateErrorText = (err) => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return err?.message || '';
};

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
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';
  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateAction, setUpdateAction] = useState('');
  const [updateNote, setUpdateNote] = useState('');
  const updateBusy = updateAction !== '';

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

  // Owner-only endpoint: don't ask for admins (they would just get a 403).
  useEffect(() => {
    if (!isOwner) return undefined;
    let cancelled = false;
    apiClient.get('/updater/status')
      .then((res) => { if (!cancelled) setUpdateInfo(res.data?.data ?? null); })
      .catch(() => { if (!cancelled) setUpdateInfo(null); });
    return () => { cancelled = true; };
  }, [isOwner]);

  const run = async (url, label) => {
    setBusy(url);
    try {
      await apiClient.post(url);
      addToast(label + ' ' + t('saved', 'done.'), 'success');
    } catch { addToast(t('error', 'Failed'), 'error'); }
    finally { setBusy(''); }
  };

  const checkUpdates = async () => {
    setUpdateAction('check');
    setUpdateNote('');
    try {
      const res = await apiClient.get('/updater/status');
      const data = res.data?.data ?? null;
      setUpdateInfo(data);
      if (data?.note) setUpdateNote(data.note);
      else if (data?.update_available) setUpdateNote(t('updateAvailableHint', 'A newer version is available.'));
      else setUpdateNote(t('updateUpToDate', 'You are running the latest version.'));
    } catch (err) {
      setUpdateNote(updateErrorText(err) || t('updateRunFailed', 'Could not start the update.'));
    } finally {
      setUpdateAction('');
    }
  };

  // The installer restarts the panel: wait for it to go down and come back.
  const pollUntilOnline = async () => {
    const deadline = Date.now() + 5 * 60 * 1000;
    await sleep(5000);
    while (Date.now() < deadline) {
      try {
        await apiClient.get('/health/overview', { timeout: 5000 });
        return true;
      } catch {
        await sleep(3000);
      }
    }
    return false;
  };

  const runUpdate = async () => {
    if (updateBusy) return;
    if (!window.confirm(t('updateConfirm', 'The panel will restart briefly and may be unavailable for up to a minute. Continue?'))) return;
    setUpdateAction('run');
    setUpdateNote('');
    try {
      const res = await apiClient.post('/updater/run');
      const body = res.data || {};
      if (!body.success) {
        // Refusals (Docker, no installer) carry the host-side command in msg.
        setUpdateNote(body.msg || t('updateRefused', 'The panel cannot start the update automatically.'));
        return;
      }
      setUpdateNote(body.msg || t('updateStarted', 'Update started. The panel will restart shortly.'));
      const backOnline = await pollUntilOnline();
      if (backOnline) {
        setUpdateNote(t('updateFinished', 'The panel is back online.'));
        addToast(t('updateFinished', 'The panel is back online.'), 'success');
        await load();
      } else {
        setUpdateNote(t('updateTimeout', 'The panel did not answer in time. Check the server logs.'));
      }
    } catch (err) {
      setUpdateNote(updateErrorText(err) || t('updateRunFailed', 'Could not start the update.'));
    } finally {
      setUpdateAction('');
    }
  };

  const spin = <span className="button-spinner" aria-hidden="true" />;

  if (loading) return <PanelSkeleton lines={4} label="Loading…" />;
  if (loadError && !sysInfo) return <ErrorState title={t('settingsLoadError', 'Failed to load settings')} message={t('settingsLoadErrorDetail', 'Could not reach the server.')} onRetry={load} retryLabel={t('retry', 'Retry')} />;

  return (
    <div className="sp-cards">
      {isOwner && (
        <Card title={t('updateCard', 'Update')} icon={FiDownload}>
          <div className="update-inline">
            <span className="update-inline-versions">
              {t('updateCurrent', 'Installed version')}: <strong>v{updateInfo?.current || '—'}</strong>
              {updateInfo?.latest && (
                <>
                  {' · '}
                  {t('updateLatest', 'Latest')}: <strong>{updateInfo.latest}</strong>
                </>
              )}
            </span>
            <div className="sp-btn-group">
              <button
                className="btn btn-sm btn-secondary"
                disabled={updateBusy}
                aria-busy={updateAction === 'check'}
                onClick={checkUpdates}
              >
                {updateAction === 'check'
                  ? spin
                  : <><FiRefreshCw size={13} aria-hidden="true" /> {t('updateCheck', 'Check for updates')}</>}
              </button>
              {updateInfo?.update_available && (
                <button
                  className="btn btn-sm"
                  disabled={updateBusy}
                  aria-busy={updateAction === 'run'}
                  onClick={runUpdate}
                >
                  {updateAction === 'run'
                    ? spin
                    : <><FiDownload size={13} aria-hidden="true" /> {t('updateNow', 'Update now')}</>}
                </button>
              )}
            </div>
          </div>
          {updateNote && <p className="sp-hint">{updateNote}</p>}
        </Card>
      )}
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
        </div>
      </Card>
    </div>
  );
};

export default SystemSection;
