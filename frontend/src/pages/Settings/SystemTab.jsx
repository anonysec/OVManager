import { useState, useEffect, useCallback } from 'react';
import { FiBarChart2, FiZap, FiRefreshCw, FiDownload } from 'react-icons/fi';
import apiClient from '../../services/api';
import { useLive } from '../../context/LiveContext';
import { formatBytes } from '../../utils/format';
import { formatUptime } from '../../utils/time';

const SystemTab = () => {
  const { refreshTick } = useLive();
  const [traffic, setTraffic] = useState({});
  const [sec, setSec] = useState(null);
  const [sysInfo, setSysInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [metricMin, setMetricMin] = useState(null);

  const addToast = (message, type = 'success') => {
    window.dispatchEvent(new CustomEvent('addToast', { detail: { message, type } }));
  };

  const loadInfo = useCallback(async () => {
    try {
      const [infoRes, metricsHistRes, loginRes] = await Promise.all([
        apiClient.get('/server/info'),
        apiClient.get('/metrics/history?hours=24'),
        apiClient.get('/maintenance/login-health?hours=8'),
        apiClient.get('/notifications/'),
        apiClient.get('/metrics/history?hours=24'),
      ]);
      setSysInfo(infoRes.data?.data || {});
      const histData = metricsHistRes.data?.data || [];
      if (Array.isArray(histData) && histData.length > 0) {
        const totalBytes = histData.reduce((s, h) => s + (h.bytes_in || 0) + (h.bytes_out || 0), 0);
        setMetricMin(totalBytes);
      }
      setTraffic(infoRes.data?.data?.traffic || infoRes.data?.data || {});
      setSec(loginRes.data?.data || null);
    } catch { /* noop */ }
  }, []);

  useEffect(() => { loadInfo(); }, [loadInfo, refreshTick]);

  const runAction = useCallback(async (url, successMsg) => {
    setBusy(true);
    try {
      await apiClient.post(url);
      addToast(successMsg || 'Action completed', 'success');
      loadInfo();
    } catch {
      addToast('Action failed', 'error');
    } finally {
      setBusy(false);
    }
  }, [loadInfo]);

  const collectMetrics = () => runAction('/metrics/collect', 'Metrics collected');
  const syncLimits = () => runAction('/maintenance/sync-limits', 'Limits synced');
  const cleanStale = () => runAction('/maintenance/clean-stale', 'Stale cleaned');
  const cleanRegistry = () => runAction('/maintenance/clean-global-registry', 'Registry cleaned');

  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiBarChart2 /> Metrics</div>
        <div className="setting-card-body">
          <div className="metric-mini-grid">
            <div className="metric-mini"><div className="metric-label">Active Connections</div><div className="metric-value">{traffic.active_connections || traffic.active || 0}</div></div>
            <div className="metric-mini"><div className="metric-label">Traffic (24h)</div><div className="metric-value">{metricMin != null ? formatBytes(metricMin) : '—'}</div></div>
            <div className="metric-mini"><div className="metric-label">Login Health</div><div className="metric-value">{sec?.totals?.online || 0}/{sec?.totals?.users || 0}</div></div>
          </div>
          <div className="card-actions">
            <button className="btn btn-sm" onClick={collectMetrics} disabled={busy}><FiZap size={14} /> Collect now</button>
          </div>
        </div>
      </div>

      <div className="setting-card">
        <div className="setting-card-header"><FiZap /> Maintenance</div>
        <div className="setting-card-body">
          <div className="card-actions">
            <button className="btn btn-sm" onClick={syncLimits} disabled={busy}><FiZap size={14} /> Sync limits</button>
            <button className="btn btn-sm btn-secondary" onClick={cleanStale} disabled={busy}><FiRefreshCw size={14} /> Clean stale</button>
            <button className="btn btn-sm btn-secondary" onClick={cleanRegistry} disabled={busy}><FiBarChart2 size={14} /> Clean registry</button>
          </div>
        </div>
      </div>

      {sysInfo && (
        <div className="setting-card">
          <div className="setting-card-header"><FiBarChart2 /> Server Info</div>
          <div className="setting-card-body">
            <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
              <div className="metric-mini"><div className="metric-label">Uptime</div><div className="metric-value">{formatUptime(sysInfo.uptime)}</div></div>
              <div className="metric-mini"><div className="metric-label">Platform</div><div className="metric-value" style={{ fontSize: 14 }}>{sysInfo.platform || '—'}</div></div>
              <div className="metric-mini"><div className="metric-label">Version</div><div className="metric-value" style={{ fontSize: 14 }}>{sysInfo.version || '—'}</div></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SystemTab;
