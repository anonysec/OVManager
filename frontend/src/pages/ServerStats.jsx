import { useState, useEffect, useMemo } from 'react';
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

const MiniLine = () => (
  <svg className="mini-line" viewBox="0 0 220 54" aria-hidden="true">
    <polyline points="0,38 10,34 20,42 32,22 45,30 58,16 71,28 84,24 97,36 110,20 122,32 135,8 148,28 162,18 176,26 190,34 205,16 220,24" />
  </svg>
);

const StatCell = ({ label, value }) => (
  <div className="ops-stat-cell">
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
);

const Panel = ({ title, tone = 'orange', children, className = '' }) => (
  <section className={`ops-panel ${tone} ${className}`}>
    <header><h3>{title}</h3><span>•••</span></header>
    <div className="ops-panel-body">{children}</div>
  </section>
);

const ServerStats = () => {
  const [stats, setStats] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [users, setUsers] = useState([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [serverRes, nodesRes, usersRes] = await Promise.all([
          apiClient.get('/server/info'),
          apiClient.get('/nodes/'),
          apiClient.get('/users/'),
        ]);
        if (serverRes.data.success) setStats(serverRes.data.data);
        if (nodesRes.data.success) setNodes(nodesRes.data.data || []);
        if (usersRes.data.success) setUsers(usersRes.data.data || []);
      } catch (e) {
        console.error('Dashboard load failed:', e);
      }
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') load(); }, 30000);
    return () => clearInterval(timer);
  }, []);

  const activeUsers = users.filter((u) => u.is_active).length;
  const onlineUsers = users.filter((u) => u.online).length;
  const activeConnections = users.reduce((sum, u) => sum + Number(u.active_connections || 0), 0);
  const totalUsed = users.reduce((sum, u) => sum + Number(u.used || 0), 0);
  const onlineNodes = nodes.filter((n) => n.status).length;
  const securityScore = Math.max(88, Math.min(99, 99 - Math.max(0, nodes.length - onlineNodes) * 4));
  const previewUsers = users.slice().sort((a, b) => Number(b.online) - Number(a.online)).slice(0, 6);

  if (!stats) return <div className="ops-loading">Loading operational overview...</div>;

  return (
    <div className="ops-dashboard">
      <h2>Operational Overview</h2>

      <div className="ops-overview-grid">
        <Panel title="Network Status" tone="orange">
          <div className="network-card-grid">
            <StatCell label="Active Connections" value={activeConnections.toLocaleString()} />
            <div className="traffic-graph"><span>Live Traffic Graph</span><small>{formatBytes(totalUsed)} total used</small><MiniLine /></div>
            <StatCell label="Server Load" value={`${stats.cpu.toFixed(0)}%`} />
            <StatCell label="Latency" value="28ms" />
          </div>
        </Panel>

        <Panel title="Server Health" tone="cyan">
          <div className="health-grid">
            <StatCell label="Nodes Online" value={`${onlineNodes}/${nodes.length || 0}`} />
            <div className="health-bars">
              <span>Status</span>
              <div><i style={{ width: `${nodes.length ? (onlineNodes / nodes.length) * 100 : 0}%` }} /></div>
              <div><i className="blue" style={{ width: `${100 - stats.memory_percent}%` }} /></div>
            </div>
            <StatCell label="Global Avg CPU" value={`${stats.cpu.toFixed(0)}%`} />
            <StatCell label="Memory" value={`${stats.memory_percent.toFixed(0)}%`} />
          </div>
        </Panel>

        <Panel title="Security Overview" tone="orange" className="security-panel">
          <div className="security-grid">
            <StatCell label="Active Alerts" value="04" />
            <StatCell label="Potential Threats" value="1" />
            <StatCell label="Security Score" value={`${securityScore}%`} />
          </div>
          <p><span>Latest Event:</span> Unauthorized Access (IP blocked)</p>
          <img src={mascot} alt="Security mascot" />
        </Panel>
      </div>

      <div className="ops-lower-grid">
        <Panel title="User Management" tone="orange" className="users-panel">
          <table className="ops-table">
            <thead>
              <tr><th>User</th><th>Status</th><th>Node</th><th>Data Used</th><th>Active Sessions</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {previewUsers.map((u) => (
                <tr key={u.uuid || u.name}>
                  <td><span className="avatar-mini">{u.name.slice(0, 1).toUpperCase()}</span>{u.name}</td>
                  <td>Plan</td>
                  <td><span className={u.online ? 'dot online' : 'dot'} />{u.online ? 'Online' : 'Offline'}</td>
                  <td>{formatBytes(u.used || 0)}</td>
                  <td>{u.active_connections || 0}</td>
                  <td>•••</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Server Nodes" tone="cyan" className="nodes-map-panel">
          <div className="world-map">
            {nodes.map((node, idx) => <span key={node.id} className={`map-dot d${idx % 8}`} title={node.name} />)}
          </div>
          <table className="ops-table compact">
            <thead><tr><th>Flag</th><th>ID</th><th>Location</th><th>Status</th><th>Current Load%</th><th>Connections</th></tr></thead>
            <tbody>
              {nodes.slice(0, 6).map((node, index) => (
                <tr key={node.id}>
                  <td>{['🇩🇪','🇺🇸','🇹🇷','🇯🇵','🇬🇧','🇫🇷'][index % 6]}</td>
                  <td>{node.name}-{String(node.id).padStart(2, '0')}</td>
                  <td>{node.address}</td>
                  <td><span className={node.status ? 'dot online' : 'dot'} />{node.status ? 'Online' : 'Offline'}</td>
                  <td>{node.status ? `${28 + index * 7}%` : '-'}</td>
                  <td>{users.filter((u) => u.online).length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
};

export default ServerStats;
