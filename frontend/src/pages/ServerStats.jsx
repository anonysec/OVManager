import { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { geoEquirectangular, geoPath } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import worldAtlas from 'world-atlas/countries-110m.json';
import apiClient, { urlPath } from '../services/api';
import { FiShield, FiActivity, FiServer, FiUsers, FiCpu, FiThermometer, FiWifi, FiAlertTriangle, FiClock, FiGlobe, FiHardDrive } from 'react-icons/fi';
import { fmtRelative, daysUntil, formatUptime } from '../utils/time';

const formatBytes = (bytes) => {
  if (!Number(bytes)) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(1)} ${u[i]}`;
};

const CODES = {
  DE: { name: 'Germany', flag: '🇩🇪', coords: [10.4, 51.1] },
  TR: { name: 'Turkey', flag: '🇹🇷', coords: [35.2, 39.1] },
  FL: { name: 'Finland', flag: '🇫🇮', coords: [25.7, 61.9] },
  FR: { name: 'France', flag: '🇫🇷', coords: [2.2, 46.6] },
  NL: { name: 'Netherlands', flag: '🇳🇱', coords: [5.3, 52.1] },
  USA: { name: 'USA', flag: '🇺🇸', coords: [-98.5, 39.8] },
  AE: { name: 'UAE', flag: '🇦🇪', coords: [54, 24] },
  RU: { name: 'Russia', flag: '🇷🇺', coords: [90, 61.5] },
  GB: { name: 'UK', flag: '🇬🇧', coords: [-1.5, 52.5] },
  CA: { name: 'Canada', flag: '🇨🇦', coords: [-106, 56] },
  SG: { name: 'Singapore', flag: '🇸🇬', coords: [103.8, 1.35] },
  JP: { name: 'Japan', flag: '🇯🇵', coords: [138, 36] },
};
const nodeMeta = (node) => {
  const code = String(node.name || '').toUpperCase();
  return CODES[code] || { name: node.name || 'Node', flag: '🏳️', coords: [20, 25] };
};

const Panel = ({ title, tone = 'orange', icon: Icon, tip, className = '', children }) => (
  <section className={`ops-panel ${tone === 'cyan' ? 'cyan' : ''} ${className}`}>
    <header><h3><Icon style={{ verticalAlign: -3, marginRight: 8 }} />{title}</h3>{tip && <span className="has-tip panel-tip" data-tip={tip} aria-label="info" />}</header>
    <div className="ops-panel-body">{children}</div>
  </section>
);

const Skeleton = ({ lines = 3 }) => (
  <div className="panel-skeleton">
    {Array.from({ length: lines }).map((_, i) => <span key={i} className="sk-line" style={{ width: `${90 - i * 12}%` }} />)}
  </div>
);

const StatCell = ({ label, value, tip, tone, spark }) => (
  <div className="ops-stat-cell has-tip" data-tip={tip || ''}>
    <span>{label}</span>
    <strong className={tone === 'danger' ? 'tone-danger' : tone === 'warn' ? 'tone-warn' : tone === 'ok' ? 'tone-ok' : ''}>{value}</strong>
    {spark && spark.length > 1 && <MiniLine values={spark} />}
  </div>
);

const MiniLine = ({ values = [] }) => {
  if (!values.length) return <div className="mini-line empty" />;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => `${(i / (values.length - 1 || 1)) * 100},${100 - (v / max) * 90 - 5}`).join(' ');
  return (
    <svg className="mini-line" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="var(--orange)" strokeWidth="3" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

const WorldMap = ({ nodes, nodeStatus }) => {
  // Equirectangular, full world framed inside the viewBox (no top/bottom clipping)
  const projection = geoEquirectangular().scale(106).translate([334, 167]);
  const pathGen = geoPath(projection);
  const land = useMemo(() => feature(worldAtlas, worldAtlas.objects.countries), []);
  const borders = useMemo(() => mesh(worldAtlas, worldAtlas.objects.countries, (a, b) => a !== b), []);
  const [hover, setHover] = useState(null);
  const [zoom, setZoom] = useState(1);
  const clamp = (z) => Math.max(1, Math.min(4, Math.round(z * 10) / 10));
  return (
    <div className="map-zoom-wrap">
      <div className="map-zoom-controls" role="group" aria-label="Map zoom">
        <button type="button" className="map-zoom-btn" onClick={() => setZoom((z) => clamp(z + 0.25))} aria-label="Zoom in">+</button>
        <button type="button" className="map-zoom-btn" onClick={() => setZoom((z) => clamp(z - 0.25))} aria-label="Zoom out">−</button>
        {zoom !== 1 && <button type="button" className="map-zoom-btn map-zoom-reset" onClick={() => setZoom(1)} aria-label="Reset zoom">⤢</button>}
      </div>
      <div className="map-zoom-viewport" style={{ overflow: zoom > 1 ? 'auto' : 'hidden' }}>
        <svg className="world-map-real" viewBox="0 0 668 334" preserveAspectRatio="xMidYMid meet"
          style={{ transform: `scale(${zoom})`, transformOrigin: 'top left', width: '100%', height: 'auto' }}
          onMouseLeave={() => setHover(null)}>
          <defs>
            <radialGradient id="sphereGrad" cx="50%" cy="38%" r="65%">
              <stop offset="0%" stopColor="#13314a" />
              <stop offset="60%" stopColor="#0c2236" />
              <stop offset="100%" stopColor="#081320" />
            </radialGradient>
          </defs>
          <path className="sphere" d={pathGen({ type: 'Sphere' }) || ''} />
          {land.features.map((feat) => (
            <path
              key={feat.id || feat.properties.name}
              className="country"
              d={pathGen(feat) || ''}
              onMouseOver={() => setHover(feat.properties.name)}
            >
              <title>{feat.properties.name}</title>
            </path>
          ))}
          <path className="country-borders" d={pathGen(borders) || ''} />
          {hover && (() => {
            const c = pathGen.centroid(land.features.find((f) => f.properties.name === hover)) || [300, 150];
            return <text x={c[0]} y={c[1]} className="country-label">{hover}</text>;
          })()}
          {nodes.map((node) => {
            const m = nodeMeta(node);
            const [x, y] = projection(m.coords) || [0, 0];
            const st = nodeStatus[node.id] || {};
            const online = node.status && st.session_diagnostics?.live_count != null && st.node_info !== undefined;
            return (
              <g key={node.id} className="map-marker" transform={`translate(${x},${y})`}>
                {online && <circle className="pulse" r={6} />}
                <circle r={online ? 5 : 3.5} className={online ? 'node-online' : 'node-offline'} />
                <text x={7} y={4} className="node-country-label">{node.name}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
};

const SecurityScoreRing = ({ score }) => {
  const r = 34; const c = 2 * Math.PI * r;
  const off = c - (score / 100) * c;
  const color = score >= 85 ? '#2ff0d4' : score >= 65 ? '#ffb454' : '#ff7a8a';
  return (
    <svg className="score-ring" width="92" height="92" viewBox="0 0 92 92">
      <circle cx="46" cy="46" r={r} className="ring-bg" />
      <circle cx="46" cy="46" r={r} className="ring-fg" stroke={color}
        strokeDasharray={c} strokeDashoffset={off} transform="rotate(-90 46 46)" />
      <text x="46" y="46" className="ring-num" fill={color}>{score}</text>
    </svg>
  );
};

const deriveNotifications = ({ users, nodes, nodeStatus, security }) => {
  const out = [];
  (nodes || []).forEach((n) => {
    if (!n.status) return; // DB-inactive nodes aren't "down"
    const st = nodeStatus?.[n.id] || {};
    if (st.session_diagnostics === undefined || st.node_info === undefined) {
      out.push({ id: `node-${n.id}`, level: 'danger', title: `Node ${n.name} unreachable`, detail: 'No API response from OVNode', action: null });
    }
  });
  (users || []).forEach((u) => {
    const d = daysUntil(u.expiry_date);
    if (Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins)) {
      out.push({ id: `full-${u.uuid}`, level: 'warning', title: `User ${u.name} at max logins`, detail: `${u.active_connections}/${u.max_logins} sessions`, action: null });
    }
  });
  const sec = security || {};
  if (Number(sec.auth_errors || 0) > 0) out.push({ id: 'auth', level: 'danger', title: `${sec.auth_errors} auth errors (8h)`, detail: 'Failed authentications across nodes', action: null });
  if (Number(sec.rejects || 0) > 0) out.push({ id: 'rej', level: 'warning', title: `${sec.rejects} connection rejects (8h)`, detail: 'OVNode connection rejects', action: null });
  return out;
};

const ServerStats = () => {
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState(null);
  const [nodes, setNodes] = useState(null);
  const [nodeStatus, setNodeStatus] = useState({});
  const [metrics, setMetrics] = useState(null);
  const [security, setSecurity] = useState(null);
  const [trafficHistory, setTrafficHistory] = useState([]);

  useEffect(() => {
    const load = async () => {
      let nodesData = [];
      try {
        const [statsRes, usersRes, nodesRes, metricsRes, secRes] = await Promise.all([
          apiClient.get('/server/info'),
          apiClient.get('/users/'),
          apiClient.get('/nodes/'),
          apiClient.get('/metrics'),
          apiClient.get('/security/summary?hours=8'),
        ]);
        setStats(statsRes.data?.data || null);
        setUsers(usersRes.data?.data || []);
        nodesData = nodesRes.data?.data || [];
        setNodes(nodesData);
        setMetrics(metricsRes.data?.data || null);
        setSecurity(secRes.data?.data || null);
        const lastTraffic = (metricsRes.data?.data?.traffic || []).at(-1);
        const point = Number(lastTraffic?.active_connections ?? 0);
        setTrafficHistory((h) => [...h.slice(-19), point]);
      } catch (e) { console.error('Dashboard load failed:', e); }

      // node status: per-node, non-blocking, short timeout
      try {
        const ns = nodesData;
        const results = await Promise.all(ns.map(async (n) => {
          if (!n.status) return [n.id, { status: 'inactive', session_diagnostics: {}, node_info: {}, latency_ms: 0 }];
          try {
            const r = await apiClient.get(`/nodes/${n.id}/status/`, { timeout: 4000 });
            return [n.id, r.data?.data || {}];
          } catch (e) { return [n.id, { status: 'unreachable', session_diagnostics: undefined, node_info: undefined, latency_ms: 0 }]; }
        }));
        setNodeStatus(Object.fromEntries(results));
      } catch { /* keep previous */ }
    };
    load();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') load(); }, 30000);
    return () => clearInterval(timer);
  }, []);

  const onlineNodes = (nodes || []).filter((n) => {
    if (!n.status) return false;
    const st = nodeStatus[n.id] || {};
    return st.node_info !== undefined && st.session_diagnostics !== undefined;
  }).length;
  const activeConnections = Object.values(nodeStatus).reduce((sum, status) => sum + Number(status?.session_diagnostics?.live_count || 0), 0);
  const avgLatency = (() => {
    const values = Object.values(nodeStatus).map((s) => Number(s?.latency_ms)).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
  })();
  const totalUsed = (users || []).reduce((sum, u) => sum + Number(u.used || 0), 0);
  const trafficTrend = (metrics?.traffic || []).map((p) => Number(p.active_connections || 0));
  const avgNodeCpu = (() => {
    const values = Object.values(nodeStatus).map((s) => Number(s?.node_info?.cpu_usage)).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : Number(stats?.cpu || 0);
  })();
  const avgNodeMem = (() => {
    const values = Object.values(nodeStatus).map((s) => Number(s?.node_info?.memory_usage)).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : Number(stats?.memory_percent || 0);
  })();
  const offlineNodes = (nodes || []).length - onlineNodes;
  const fullUsers = (users || []).filter((u) => Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins || 0));
  const activeAlerts = offlineNodes + fullUsers.length;

  const sec = security || {};
  const authErrors = Number(sec.auth_errors || 0);
  const rejects = Number(sec.rejects || 0);
  const stale = Number(sec.stale_markers || 0);
  const penalty = offlineNodes * 8 + fullUsers.length * 3 + Math.min(authErrors, 50) * 0.6 + Math.min(rejects, 50) * 0.4 + Math.min(stale, 50) * 0.4;
  const securityScore = Math.max(0, Math.min(100, Math.round(100 - penalty)));
  const latestErrors = sec.last_errors || [];
  const notifications = deriveNotifications({ users, nodes, nodeStatus, security });
  const previewUsers = (users || [])
    .filter((u) => Number(u.active_connections || 0) > 0)
    .sort((a, b) => Number(b.active_connections || 0) - Number(a.active_connections || 0))
    .slice(0, 6);

  return (
    <div className="ops-dashboard compact">
      <h2>{t('operationalOverview')}</h2>

      <div className="ops-overview-grid">
        <Panel title={t('networkStatus')} tone="orange" icon={FiActivity} tip={t('networkStatus')}>
          {stats && users && nodes ? (
            <div className="network-card-grid">
              <StatCell label={t('activeConnections')} value={activeConnections.toLocaleString()} tip={t('activeConnections')} spark={trafficHistory} />
              <StatCell label={t('totalTraffic')} value={formatBytes(totalUsed)} tip={t('totalTraffic')} spark={trafficHistory.map((v) => v * 8)} />
              <StatCell label={t('onlineNodes')} value={`${onlineNodes}/${nodes.length || 0}`} tip={t('onlineNodes')} tone={offlineNodes ? 'warn' : 'ok'} />
              <StatCell label={t('avgLatency')} value={avgLatency ? `${avgLatency.toFixed(0)}ms` : '-'} tip={t('avgLatency')} />
            </div>
          ) : <Skeleton />}
        </Panel>

        <Panel title={t('serverHealth')} tone="cyan" icon={FiServer} tip={t('serverHealth')}>
          {stats ? (
            <div className="health-grid">
              <StatCell label={t('panelCPU')} value={`${stats.cpu.toFixed(0)}%`} tip={t('panelCPU')} tone={stats.cpu > 85 ? 'danger' : stats.cpu > 70 ? 'warn' : 'ok'} />
              <StatCell label={t('panelMemory')} value={`${stats.memory_percent.toFixed(0)}%`} tip={t('panelMemory')} tone={stats.memory_percent > 85 ? 'danger' : stats.memory_percent > 70 ? 'warn' : 'ok'} />
              <StatCell label={t('disk')} value={`${stats.disk_percent.toFixed(0)}%`} tip={t('disk')} tone={stats.disk_percent > 85 ? 'danger' : 'ok'} />
              <StatCell label={t('nodesOnline')} value={`${onlineNodes}/${nodes?.length || 0}`} tip={t('nodesOnline')} tone={offlineNodes ? 'warn' : 'ok'} />
            </div>
          ) : <Skeleton />}
          <div className="resource-chips">
            <span><FiCpu /> {stats ? stats.cpu.toFixed(0) : '–'}% CPU</span>
            <span><FiThermometer /> {stats ? stats.memory_percent.toFixed(0) : '–'}% Mem</span>
            <span><FiHardDrive /> {stats ? stats.disk_percent.toFixed(0) : '–'}% Disk</span>
            <span><FiWifi /> {onlineNodes} nodes</span>
          </div>
        </Panel>

        <Panel title={t('securityOverview')} tone="orange" className="security-panel" icon={FiShield} tip={t('securityOverview')}>
          {security ? (
            <>
              <div className="security-flex">
                <SecurityScoreRing score={securityScore} />
                <div className="security-facts">
                  <StatCell label={t('activeAlerts')} value={String(activeAlerts).padStart(2, '0')} tip={t('activeAlerts')} tone={activeAlerts ? 'warn' : 'ok'} />
                  <StatCell label={t('authErrors8h')} value={String(authErrors)} tip={t('authErrors8h')} tone={authErrors ? 'danger' : 'ok'} />
                  <StatCell label={t('rejects8h')} value={String(rejects)} tip={t('rejects8h')} tone={rejects ? 'warn' : 'ok'} />
                </div>
              </div>
              <p className={`security-verdict ${securityScore >= 85 ? 'ok' : securityScore >= 65 ? 'warn' : 'bad'}`}>
                {securityScore >= 85 ? t('verdictHealthy')
                  : securityScore >= 65 ? t('verdictWatch')
                  : t('verdictCritical')}
              </p>
              {latestErrors.length > 0 && (
                <ul className="security-errors">
                  {latestErrors.slice(0, 3).map((e, i) => (
                    <li key={i}>{e.time_tehran || ''} — {e.common_name}: {e.reason} ({e.active || '?'}/{e.limit || '?'})</li>
                  ))}
                </ul>
              )}
            </>
          ) : <Skeleton />}
        </Panel>
      </div>

      <div className="ops-lower-grid">
        <Panel title={t('onlineUsers')} tone="orange" className="users-panel" icon={FiUsers} tip={t('onlineUsers')}>
          {users ? (
            <>
              <table className="ops-table">
                <thead>
                  <tr><th>{t('th_user')}</th><th>{t('th_plan')}</th><th>{t('th_status')}</th><th>{t('th_dataUsed')}</th><th>{t('th_sessions')}</th><th>{t('th_lastOnline')}</th><th>{t('th_actions')}</th></tr>
                </thead>
                <tbody>
                  {previewUsers.map((u) => (
                    <tr key={u.uuid || u.name} title={`${u.name}: ${u.active_connections || 0}/${u.max_logins || '∞'} sessions, ${formatBytes(u.used || 0)} used`}>
                      <td><span className="avatar-mini">{u.name.slice(0, 1).toUpperCase()}</span>{u.name}</td>
                      <td>{u.max_logins === 0 ? t('unlimited') : t('devicesCount', { count: u.max_logins })}</td>
                      <td><span className={u.online ? 'dot online' : 'dot'} />{u.online ? t('statusOnline') : t('statusOffline')}</td>
                      <td>{formatBytes(u.used || 0)}</td>
                      <td>{u.active_connections || 0}</td>
                      <td className="col-last-online">{u.online ? t('statusOnline') : fmtRelative(u.last_online)}</td>
                      <td><button type="button" className="mini-btn" title={`${t('manage')} ${u.name}`} onClick={() => window.location.assign(`${urlPath}/users?user=${u.uuid}`)}>{t('manage')}</button></td>
                    </tr>
                  ))}
                  {previewUsers.length === 0 && <tr><td colSpan="7" style={{ textAlign: 'center', color: 'var(--muted)' }}>{t('noUsersOnline')}</td></tr>}
                </tbody>
              </table>
            </>
          ) : <Skeleton />}
        </Panel>

        <Panel title={t('serverNodes')} tone="cyan" className="nodes-map-panel" icon={FiGlobe} tip={t('serverNodes')}>
          {nodes ? (
            <>
              <WorldMap nodes={nodes} nodeStatus={nodeStatus} />
              <table className="ops-table compact">
                <thead><tr><th>{t('th_id')}</th><th>{t('th_location')}</th><th>{t('th_status')}</th><th>{t('th_cpu')}</th><th>{t('th_conns')}</th></tr></thead>
                <tbody>
                  {nodes.slice(0, 8).map((node) => {
                    const meta = nodeMeta(node);
                    const status = nodeStatus[node.id] || {};
                    const cpu = status.node_info?.cpu_usage;
                    const conns = Number(status.session_diagnostics?.live_count || 0);
                    const reachable = node.status && status.node_info !== undefined;
                    return (
                      <tr key={node.id} title={`${node.name}: ${conns} live sessions, API ${node.address}:${node.port}`}>
                        <td>{node.name}</td>
                        <td>{meta.name}</td>
                        <td><span className={reachable ? 'dot online' : 'dot'} />{reachable ? t('statusOnline') : (node.status ? t('statusDown') : t('statusOff'))}</td>
                        <td>{Number.isFinite(Number(cpu)) ? `${Number(cpu).toFixed(0)}%` : '-'}</td>
                        <td>{conns} <small className="latency-note">{status.latency_ms ? `${status.latency_ms}ms` : ''}</small></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          ) : <Skeleton />}
        </Panel>
      </div>

      {notifications.length > 0 && (
        <div className="ops-notice-strip">
          <FiAlertTriangle /> {notifications.length} {t(notifications.length === 1 ? 'alertOne' : 'alertsMany')}:{' '}
          {notifications.slice(0, 4).map((n) => <span key={n.id} className={`ntag ${n.level}`}>{n.title}</span>)}
          {notifications.length > 4 && <span className="ntag">{t('moreN', { count: notifications.length - 4 })}</span>}
        </div>
      )}
    </div>
  );
};

export default ServerStats;
