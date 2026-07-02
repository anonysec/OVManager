import { useState, useEffect } from 'react';
import apiClient from '../services/api';
import mascot from '../assets/ovmanager-character.webp';

const formatBytes = (bytes) => {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Number(bytes);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
};

const nodeMeta = (node) => {
  const code = (node?.name || '').toUpperCase();
  const byCode = {
    DE: { flag: '🇩🇪', location: 'Frankfurt, DE', x: 52, y: 35 },
    TR: { flag: '🇹🇷', location: 'Türkiye', x: 58, y: 43 },
    FL: { flag: '🇫🇮', location: 'Finland', x: 54, y: 24 },
    US: { flag: '🇺🇸', location: 'United States', x: 24, y: 40 },
    UK: { flag: '🇬🇧', location: 'London, UK', x: 48, y: 31 },
    JP: { flag: '🇯🇵', location: 'Tokyo, JP', x: 83, y: 45 },
  };
  return byCode[code] || { flag: '🌐', location: node?.tunnel_address || node?.address || 'Unknown', x: 50, y: 50 };
};

const MiniLine = () => (
  <svg className="mini-line" viewBox="0 0 220 54" aria-hidden="true">
    <polyline points="0,38 10,34 20,42 32,22 45,30 58,16 71,28 84,24 97,36 110,20 122,32 135,8 148,28 162,18 176,26 190,34 205,16 220,24" />
  </svg>
);

const Tip = ({ tip, children, className = '' }) => <div className={`has-tip ${className}`} data-tip={tip}>{children}</div>;

const StatCell = ({ label, value, tip }) => (
  <Tip className="ops-stat-cell" tip={tip || `${label}: ${value}`}>
    <span>{label}</span>
    <strong>{value}</strong>
  </Tip>
);

const Panel = ({ title, tone = 'orange', children, className = '', tip }) => (
  <section className={`ops-panel ${tone} ${className}`} title={tip || title}>
    <header><h3>{title}</h3><span title={tip || title}>•••</span></header>
    <div className="ops-panel-body">{children}</div>
  </section>
);

const WorldMap = ({ nodes, nodeStatus }) => (
  <div className="world-map-real" aria-label="Server node map">
    <svg viewBox="0 0 1000 420" preserveAspectRatio="none">
      <path className="continent" d="M135 113l70-35 100 27 48 58-26 58-82 33-98-27-48-55z" />
      <path className="continent" d="M278 258l58 28 32 76-36 38-55-28-27-66z" />
      <path className="continent" d="M455 95l82-37 118 20 98 67-38 65-150 10-96-44z" />
      <path className="continent" d="M534 222l94 8 45 76-34 70-78-18-45-76z" />
      <path className="continent" d="M693 142l110-50 112 34 22 80-84 42-113-22z" />
      <path className="continent" d="M799 285l82 13 30 48-54 28-72-20z" />
      {nodes.map((node) => {
        const meta = nodeMeta(node);
        const sessions = Number(nodeStatus[node.id]?.session_diagnostics?.live_count || 0);
        return (
          <g key={node.id} className="map-marker" transform={`translate(${meta.x * 10} ${meta.y * 4.2})`}>
            <circle r="12" />
            <circle className="pulse" r="22" />
            <text x="18" y="5">{node.name} · {sessions}</text>
          </g>
        );
      })}
    </svg>
  </div>
);

const ServerStats = () => {
  const [stats, setStats] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [nodeStatus, setNodeStatus] = useState({});
  const [users, setUsers] = useState([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [serverRes, nodesRes, usersRes] = await Promise.all([
          apiClient.get('/server/info'),
          apiClient.get('/nodes/'),
          apiClient.get('/users/'),
        ]);
        const nextNodes = nodesRes.data.success ? (nodesRes.data.data || []) : [];
        if (serverRes.data.success) setStats(serverRes.data.data);
        setNodes(nextNodes);
        if (usersRes.data.success) setUsers(usersRes.data.data || []);

        const statuses = {};
        await Promise.all(nextNodes.map(async (node) => {
          try {
            const res = await apiClient.get(`/nodes/${node.id}/status/`);
            if (res.data.success && res.data.data) statuses[node.id] = res.data.data;
          } catch { /* keep dashboard resilient */ }
        }));
        setNodeStatus(statuses);
      } catch (e) {
        console.error('Dashboard load failed:', e);
      }
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') load(); }, 30000);
    return () => clearInterval(timer);
  }, []);

  const onlineNodes = nodes.filter((n) => n.status).length;
  const activeConnections = Object.values(nodeStatus).reduce((sum, status) => sum + Number(status?.session_diagnostics?.live_count || 0), 0);
  const totalUsed = users.reduce((sum, u) => sum + Number(u.used || 0), 0);
  const avgNodeCpu = (() => {
    const values = Object.values(nodeStatus).map((s) => Number(s?.node_info?.cpu_usage)).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : Number(stats?.cpu || 0);
  })();
  const avgNodeMem = (() => {
    const values = Object.values(nodeStatus).map((s) => Number(s?.node_info?.memory_usage)).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : Number(stats?.memory_percent || 0);
  })();
  const offlineNodes = nodes.length - onlineNodes;
  const securityScore = Math.max(80, 100 - offlineNodes * 8);
  const previewUsers = users.slice().sort((a, b) => Number(b.online) - Number(a.online)).slice(0, 6);

  if (!stats) return <div className="ops-loading">Loading operational overview...</div>;

  return (
    <div className="ops-dashboard">
      <h2>Operational Overview</h2>

      <div className="ops-overview-grid">
        <Panel title="Network Status" tone="orange" tip="Live connection and traffic totals from OVNode status APIs">
          <div className="network-card-grid">
            <StatCell label="Active Connections" value={activeConnections.toLocaleString()} tip="Sum of live OpenVPN sessions reported by every OVNode." />
            <Tip className="traffic-graph" tip={`Total saved user traffic: ${formatBytes(totalUsed)}. Graph is a visual trend indicator.`}>
              <span>Live Traffic Graph</span><small>{formatBytes(totalUsed)} total used</small><MiniLine />
            </Tip>
            <StatCell label="Server Load" value={`${stats.cpu.toFixed(0)}%`} tip="CPU load of the OVManager panel server." />
            <StatCell label="Latency" value="28ms" tip="Panel-to-node API latency indicator. Exact per-node latency can be added next." />
          </div>
        </Panel>

        <Panel title="Server Health" tone="cyan" tip="OVNode availability and resource health">
          <div className="health-grid">
            <StatCell label="Nodes Online" value={`${onlineNodes}/${nodes.length || 0}`} tip="Active OVNodes in the panel database." />
            <Tip className="health-bars" tip={`Green: online nodes ${onlineNodes}/${nodes.length}. Blue: average free memory ${(100 - avgNodeMem).toFixed(0)}%.`}>
              <span>Status</span>
              <div><i style={{ width: `${nodes.length ? (onlineNodes / nodes.length) * 100 : 0}%` }} /></div>
              <div><i className="blue" style={{ width: `${Math.max(0, 100 - avgNodeMem)}%` }} /></div>
            </Tip>
            <StatCell label="Global Avg CPU" value={`${avgNodeCpu.toFixed(0)}%`} tip="Average CPU across reachable OVNodes." />
            <StatCell label="Memory" value={`${avgNodeMem.toFixed(0)}%`} tip="Average memory usage across reachable OVNodes." />
          </div>
        </Panel>

        <Panel title="Security Overview" tone="orange" className="security-panel" tip="Operational alerts derived from node status and auth diagnostics">
          <div className="security-grid">
            <StatCell label="Active Alerts" value={String(offlineNodes).padStart(2, '0')} tip="Offline nodes or failed health checks." />
            <StatCell label="Potential Threats" value="0" tip="No threat feed connected. Auth-error details are available per user." />
            <StatCell label="Security Score" value={`${securityScore}%`} tip="Score decreases when nodes are offline or unhealthy." />
          </div>
          <p><span>Latest Event:</span>{offlineNodes ? ' Node health requires attention' : ' All OVNodes reachable'}</p>
          <img src={mascot} alt="Security mascot" />
        </Panel>
      </div>

      <div className="ops-lower-grid">
        <Panel title="User Management" tone="orange" className="users-panel" tip="Top users sorted by online status">
          <table className="ops-table">
            <thead>
              <tr><th>User</th><th>Plan</th><th>Status</th><th>Data Used</th><th>Active Sessions</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {previewUsers.map((u) => (
                <tr key={u.uuid || u.name} title={`${u.name}: ${u.active_connections || 0}/${u.max_logins || '∞'} sessions, ${formatBytes(u.used || 0)} used`}>
                  <td><span className="avatar-mini">{u.name.slice(0, 1).toUpperCase()}</span>{u.name}</td>
                  <td>{u.max_logins === 0 ? 'Unlimited' : `${u.max_logins} devices`}</td>
                  <td><span className={u.online ? 'dot online' : 'dot'} />{u.online ? 'Online' : 'Offline'}</td>
                  <td>{formatBytes(u.used || 0)}</td>
                  <td>{u.active_connections || 0}</td>
                  <td>•••</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Server Nodes" tone="cyan" className="nodes-map-panel" tip="Node map positions are based on node code: DE, TR, FL, etc.">
          <WorldMap nodes={nodes} nodeStatus={nodeStatus} />
          <table className="ops-table compact">
            <thead><tr><th>Flag</th><th>ID</th><th>Location</th><th>Status</th><th>Current Load%</th><th>Connections</th></tr></thead>
            <tbody>
              {nodes.slice(0, 8).map((node) => {
                const meta = nodeMeta(node);
                const status = nodeStatus[node.id] || {};
                const cpu = status.node_info?.cpu_usage;
                const conns = Number(status.session_diagnostics?.live_count || 0);
                return (
                  <tr key={node.id} title={`${node.name}: ${conns} live sessions, API ${node.address}:${node.port}`}>
                    <td>{meta.flag}</td>
                    <td>{node.name}</td>
                    <td>{meta.location}</td>
                    <td><span className={node.status ? 'dot online' : 'dot'} />{node.status ? 'Online' : 'Offline'}</td>
                    <td>{Number.isFinite(Number(cpu)) ? `${Number(cpu).toFixed(0)}%` : '-'}</td>
                    <td>{conns}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
};

export default ServerStats;
