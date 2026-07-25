import { FiBarChart2, FiZap, FiRefreshCw } from 'react-icons/fi';

const SystemTab = ({ t, traffic, runAction, metricMin, sec }) => {
  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiBarChart2 /> Metrics</div>
        <div className="setting-card-body">
          <div className="metric-mini-grid">
            <div className="metric-mini"><div className="metric-label">Active Connections</div><div className="metric-value">{traffic.active_connections || 0}</div></div>
            <div className="metric-mini"><div className="metric-label">Traffic</div><div className="metric-value">{metricMin(traffic.total_used || 0)}</div></div>
            <div className="metric-mini"><div className="metric-label">Login Health</div><div className="metric-value">{sec?.totals?.online || 0}/{sec?.totals?.users || 0}</div></div>
          </div>
          <div className="card-actions">
            <button className="btn btn-sm" onClick={() => runAction('/metrics/collect', 'Metrics collected')}><FiZap size={14} /> Collect now</button>
          </div>
        </div>
      </div>

      <div className="setting-card">
        <div className="setting-card-header"><FiZap /> Maintenance</div>
        <div className="setting-card-body">
          <div className="card-actions">
            <button className="btn btn-sm" onClick={() => runAction('/maintenance/sync-limits', 'Limits synced')}><FiZap size={14} /> Sync limits</button>
            <button className="btn btn-sm btn-secondary" onClick={() => runAction('/maintenance/clean-stale', 'Stale cleaned')}><FiRefreshCw size={14} /> Clean stale</button>
            <button className="btn btn-sm btn-secondary" onClick={() => runAction('/maintenance/clean-global-registry', 'Registry cleaned')}><FiBarChart2 size={14} /> Clean registry</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SystemTab;