// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { useLive } from '../../context/LiveContext';
import { useAuth } from '../../context/AuthContext';
import apiClient from '../../services/api';
import { settle } from '../../hooks/useAsyncData';
import { PanelSkeleton } from '../../components/ui';
import ErrorState from '../../components/ui/ErrorState';
import { FiServer, FiZap, FiRefreshCw, FiDownload, FiPower, FiTrash2 } from 'react-icons/fi';
import { Card, Field, Stat } from './shared';
import { formatBytes } from '../../utils/format';
import { formatUptime } from '../../utils/time';
import '../UpdateNotice.css';

const sleep = (ms: number) => new Promise((resolve) => { setTimeout(resolve, ms); });

interface SysInfo {
  uptime: number | string;
  cpu: number;
  memory_percent: number;
  disk_percent: number;
}

interface UpdateInfo {
  current?: string;
  latest?: string;
  update_available?: boolean;
  note?: string;
}

const updateErrorText = (err: any) => {
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
  const [sysInfo, setSysInfo] = useState<SysInfo | null>(null);
  const [trafficTotal, setTrafficTotal] = useState<number | null>(null);
  const [activeConns, setActiveConns] = useState(0);
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const { userRole } = useAuth() as unknown as { userRole: string | null };
  const isOwner = userRole === 'owner';
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updateAction, setUpdateAction] = useState('');
  const [updateNote, setUpdateNote] = useState('');
  const updateBusy = updateAction !== '';

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(false);
      const res: any = await settle({
        info: apiClient.get('/server/info'),
        metrics: apiClient.get('/metrics/history?hours=24'),
      });
      if (res.info.ok) setSysInfo(res.info.data.data?.data || null);
      else setLoadError(true);
      const traffic = res.metrics.ok ? (res.metrics.data.data?.data?.traffic || []) : [];
      if (traffic.length) {
        setTrafficTotal(traffic.reduce((s: number, h: any) => s + Number(h.total_used || 0), 0));
        setActiveConns(traffic[traffic.length - 1]?.active_connections || 0);
      }
    } catch { setLoadError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  useEffect(() => {
    if (!isOwner) return undefined;
    let cancelled = false;
    apiClient.get('/updater/status')
      .then((res) => { if (!cancelled) setUpdateInfo(res.data?.data ?? null); })
      .catch(() => { if (!cancelled) setUpdateInfo(null); });
    return () => { cancelled = true; };
  }, [isOwner]);

  const run = async (url: string, label: string) => {
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

  const restartPanel = async () => {
    if (busy) return;
    if (!window.confirm(t('restartConfirm', 'The panel will restart briefly and may be unavailable for up to a minute. Continue?'))) return;
    setBusy('/maintenance/restart');
    try {
      const res = await apiClient.post('/maintenance/restart');
      const body = res.data || {};
      if (!body.success) {
        addToast(body.msg || t('error', 'Failed'), 'error');
        return;
      }
      addToast(body.msg || t('restartStarted', 'Restarting panel…'), 'success');
      const backOnline = await pollUntilOnline();
      if (backOnline) {
        addToast(t('restartFinished', 'The panel is back online.'), 'success');
        await load();
      } else {
        addToast(t('restartTimeout', 'The panel did not answer in time. Check the server logs.'), 'error');
      }
    } catch (err) {
      addToast(updateErrorText(err) || t('error', 'Failed'), 'error');
    } finally {
      setBusy('');
    }
  };

  const spin = <span className="button-spinner" aria-hidden="true" />;

  /* ── Manual cleanup: preview first, delete only on confirm ── */
  const [cleanStatus, setCleanStatus] = useState('expired');
  const [cleanDays, setCleanDays] = useState('0');
  const [cleanBusy, setCleanBusy] = useState(''); // 'preview' | 'run' | 'reset'
  const [cleanNote, setCleanNote] = useState('');
  const cleanKey = `${cleanStatus}:${cleanDays}`;
  const [cleanPreviewed, setCleanPreviewed] = useState(''); // filter key of the last preview

  const cleanBody = () => ({ status: cleanStatus, older_than_days: Number(cleanDays) || 0 });

  const previewCleanup = async () => {
    if (cleanBusy) return;
    setCleanBusy('preview');
    setCleanNote('');
    try {
      const res = await apiClient.post('/maintenance/cleanup/preview', cleanBody());
      const body = res.data || {};
      if (!body.success) { addToast(body.msg || t('error', 'Failed'), 'error'); return; }
      const d = body.data || {};
      const names: string[] = d.sample || [];
      setCleanPreviewed(cleanKey);
      setCleanNote(`${t('cleanupMatched', { count: d.matched ?? 0 })}${names.length ? ` · ${names.slice(0, 5).join(', ')}` : ''}`);
    } catch (err) {
      addToast(updateErrorText(err) || t('error', 'Failed'), 'error');
    } finally { setCleanBusy(''); }
  };

  const deleteCleanup = async () => {
    if (cleanBusy || cleanPreviewed !== cleanKey) return;
    if (!window.confirm(t('cleanupDeleteConfirm', 'Permanently delete the matching users and their usage rows? This cannot be undone.'))) return;
    setCleanBusy('run');
    try {
      const res = await apiClient.post('/maintenance/cleanup/run', { ...cleanBody(), confirm: true });
      const body = res.data || {};
      if (!body.success) { addToast(body.msg || t('error', 'Failed'), 'error'); return; }
      setCleanPreviewed(''); // counts changed; preview again before the next delete
      setCleanNote(t('cleanupDeleted', { count: body.data?.deleted ?? 0 }));
    } catch (err) {
      addToast(updateErrorText(err) || t('error', 'Failed'), 'error');
    } finally { setCleanBusy(''); }
  };

  const resetAllUsage = async () => {
    if (cleanBusy) return;
    if (!window.confirm(t('cleanupResetConfirm', 'Zero the usage counters of every user? Daily history is kept.'))) return;
    setCleanBusy('reset');
    try {
      const res = await apiClient.post('/maintenance/usage/reset-all', { confirm: true });
      const body = res.data || {};
      if (!body.success) { addToast(body.msg || t('error', 'Failed'), 'error'); return; }
      setCleanNote(t('cleanupResetDone', { count: body.data?.reset ?? 0 }));
    } catch (err) {
      addToast(updateErrorText(err) || t('error', 'Failed'), 'error');
    } finally { setCleanBusy(''); }
  };

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
          <button className="btn btn-sm btn-secondary" disabled={!!busy} aria-busy={busy === '/maintenance/restart'} onClick={restartPanel}>
            {busy === '/maintenance/restart' ? spin : <><FiPower size={13} aria-hidden="true" /> {t('restartPanel', 'Restart panel')}</>}
          </button>
        </div>
        {isOwner && (
          <>
            <p className="sp-hint sp-mt-18">{t('cleanupDesc', 'Bulk-delete expired or disabled users. Preview first — nothing is deleted until you confirm.')}</p>
            <div className="sp-two-col">
              <Field label={t('status', 'Status')} inputId="cleanup-status">
                <select
                  id="cleanup-status"
                  className="sp-select"
                  value={cleanStatus}
                  disabled={!!cleanBusy}
                  onChange={(e) => { setCleanStatus(e.target.value); setCleanPreviewed(''); }}
                >
                  <option value="expired">{t('expired', 'Expired')}</option>
                  <option value="disabled">{t('disabled', 'Disabled')}</option>
                  <option value="all">{t('cleanupAll', 'Expired or disabled')}</option>
                </select>
              </Field>
              <Field label={t('cleanupOlderThan', 'Older than (days)')} inputId="cleanup-days">
                <input
                  id="cleanup-days"
                  className="sp-input"
                  type="number"
                  min={0}
                  max={3650}
                  value={cleanDays}
                  disabled={!!cleanBusy}
                  onChange={(e) => { setCleanDays(e.target.value); setCleanPreviewed(''); }}
                />
              </Field>
            </div>
            <div className="sp-btn-group sp-mt-12">
              <button className="btn btn-sm btn-secondary" disabled={!!cleanBusy} aria-busy={cleanBusy === 'preview'} onClick={previewCleanup}>
                {cleanBusy === 'preview' ? spin : t('cleanupPreviewBtn', 'Preview')}
              </button>
              <button
                className="btn btn-sm"
                disabled={!!cleanBusy || cleanPreviewed !== cleanKey}
                aria-busy={cleanBusy === 'run'}
                title={cleanPreviewed !== cleanKey ? t('cleanupPreviewFirst', 'Preview the filter first.') : undefined}
                onClick={deleteCleanup}
              >
                {cleanBusy === 'run' ? spin : <><FiTrash2 size={13} aria-hidden="true" /> {t('delete', 'Delete')}</>}
              </button>
              <button className="btn btn-sm btn-secondary" disabled={!!cleanBusy} aria-busy={cleanBusy === 'reset'} onClick={resetAllUsage}>
                {cleanBusy === 'reset' ? spin : t('resetUsageButton', 'Reset Usage')}
              </button>
            </div>
            {cleanNote && <p className="sp-hint sp-mt-12" role="status">{cleanNote}</p>}
          </>
        )}
      </Card>
    </div>
  );
};

export default SystemSection;
