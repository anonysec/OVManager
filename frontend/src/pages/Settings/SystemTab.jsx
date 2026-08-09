import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiBarChart2, FiZap, FiRefreshCw } from 'react-icons/fi';
import apiClient from '../../services/api';
import ErrorState from '../../components/ui/ErrorState';
import PanelSkeleton from '../../components/ui/PanelSkeleton';
import { useLive } from '../../context/LiveContext';
import { useToast } from '../../context/ToastContext';
import { formatBytes } from '../../utils/format';
import { formatUptime } from '../../utils/time';

const SystemTab = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [traffic, setTraffic] = useState({});
  const [sec, setSec] = useState(null);
  const [sysInfo, setSysInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [metricMin, setMetricMin] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadInfo = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [infoRes, metricsHistRes, loginRes] = await Promise.all([
        apiClient.get('/server/info'),
        apiClient.get('/metrics/history?hours=24'),
        apiClient.get('/maintenance/login-health?hours=8'),
      ]);
      setSysInfo(infoRes.data?.data || {});
      const histData = metricsHistRes.data?.data || {};
      const trafficArr = histData.traffic || [];
      if (Array.isArray(trafficArr) && trafficArr.length > 0) {
        setMetricMin(trafficArr.reduce((s, h) => s + (Number(h.total_used) || 0), 0));
      }
      setTraffic(trafficArr[trafficArr.length - 1] || {});
      setSec(loginRes.data?.data || null);
    } catch {
      setError(t('failedToLoad', 'Failed to load data'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { loadInfo(); }, [loadInfo, refreshTick]);

  const runAction = useCallback(async (url, successMsg) => {
    setBusy(true);
    try {
      await apiClient.post(url);
      addToast(successMsg, 'success');
      loadInfo();
    } catch {
      addToast(t('error', 'Action failed'), 'error');
    } finally {
      setBusy(false);
    }
  }, [loadInfo, addToast, t]);

  return (
    <div className="settings-section">
      {error && <ErrorState title={t('error', 'Error')} message={error} onRetry={loadInfo} />}
      {loading && !error && <PanelSkeleton lines={6} label={t('loading', 'Loading…')} />}
      {!error && !loading && (
        <>
          <div className="setting-card">
            <div className="setting-card-header"><FiBarChart2 /> {t('metrics', 'Metrics')}</div>
            <div className="setting-card-body">
              <div className="metric-mini-grid" aria-live="polite">
                <div className="metric-mini">
                  <div className="metric-label">{t('activeConnections', 'Active Connections')}</div>
                  <div className="metric-value">{traffic.active_connections || traffic.active || 0}</div>
                </div>
                <div className="metric-mini">
                  <div className="metric-label">{t('totalTraffic', 'Traffic (24h)')}</div>
                  <div className="metric-value">{metricMin != null ? formatBytes(metricMin) : '—'}</div>
                </div>
                <div className="metric-mini">
                  <div className="metric-label">{t('loginHealth', 'Login Health')}</div>
                  <div className="metric-value">{sec?.totals?.online || 0}/{sec?.totals?.users || 0}</div>
                </div>
              </div>
              <div className="card-actions">
                <button className="btn btn-sm" onClick={() => runAction('/metrics/collect', t('collectNow', 'Metrics collected'))} disabled={busy}>
                  <FiZap size={14} /> {t('collectNow', 'Collect now')}
                </button>
              </div>
            </div>
          </div>

          <div className="setting-card">
            <div className="setting-card-header"><FiZap /> {t('maintenance', 'Maintenance')}</div>
            <div className="setting-card-body">
              <div className="card-actions">
                <button className="btn btn-sm" onClick={() => runAction('/maintenance/sync-limits', t('syncLimits', 'Limits synced'))} disabled={busy}>
                  <FiZap size={14} /> {t('syncLimits', 'Sync limits')}
                </button>
                <button className="btn btn-sm btn-secondary" onClick={() => runAction('/maintenance/clean-stale', t('cleanStale', 'Stale cleaned'))} disabled={busy}>
                  <FiRefreshCw size={14} /> {t('cleanStale', 'Clean stale')}
                </button>
                <button className="btn btn-sm btn-secondary" onClick={() => runAction('/maintenance/clean-global-registry', t('cleanRegistry', 'Registry cleaned'))} disabled={busy}>
                  <FiBarChart2 size={14} /> {t('cleanRegistry', 'Clean registry')}
                </button>
              </div>
            </div>
          </div>

          {sysInfo && (
            <div className="setting-card">
              <div className="setting-card-header"><FiBarChart2 /> {t('serverInfo', 'Server Info')}</div>
              <div className="setting-card-body">
                <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                  <div className="metric-mini">
                    <div className="metric-label">{t('kv_uptime', 'Uptime')}</div>
                    <div className="metric-value">{formatUptime(sysInfo.uptime)}</div>
                  </div>
                  <div className="metric-mini">
                    <div className="metric-label">{t('kv_cpu', 'CPU')}</div>
                    <div className="metric-value">{sysInfo.cpu != null ? `${Number(sysInfo.cpu).toFixed(0)}%` : '—'}</div>
                  </div>
                  <div className="metric-mini">
                    <div className="metric-label">{t('version', 'Version')}</div>
                    <div className="metric-value" style={{ fontSize: 14 }}>{sysInfo.version || '—'}</div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default SystemTab;
