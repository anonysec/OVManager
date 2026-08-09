import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { geoEquirectangular, geoPath } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import worldAtlas from 'world-atlas/countries-110m.json';
import apiClient from '../services/api';
import { FiShield, FiActivity, FiServer, FiUsers, FiGlobe, FiAlertTriangle, FiCheckCircle, FiRefreshCw, FiArrowRight } from 'react-icons/fi';
import { fmtRelative } from '../utils/time';
import { ErrorState, EmptyState, PanelSkeleton, StatusBadge } from '../components/ui';

const formatBytes = (bytes) => {
  if (!Number(bytes)) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(1)} ${u[i]}`
};

const CODES = {
  DE: { name: 'Germany', coords: [10.4, 51.1] },
  TR: { name: 'Turkey', coords: [35.2, 39.1] },
  FI: { name: 'Finland', coords: [25.7, 61.9] },
  FR: { name: 'France', coords: [2.2, 46.6] },
  NL: { name: 'Netherlands', coords: [5.3, 52.1] },
  USA: { name: 'USA', coords: [-98.5, 39.8] },
  AE: { name: 'UAE', coords: [54, 24] },
  RU: { name: 'Russia', coords: [90, 61.5] },
  GB: { name: 'UK', coords: [-1.5, 52.5] },
  CA: { name: 'Canada', coords: [-106, 56] },
  SG: { name: 'Singapore', coords: [103.8, 1.35] },
  JP: { name: 'Japan', coords: [138, 36] },
};

const FLAG_SVGS = {
  DE: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#ffce00"/><rect width="640" height="160" fill="#000"/><rect y="320" width="640" height="160" fill="#d00"/></svg>',
  TR: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#e30a0a"/><circle cx="220" cy="240" r="70" fill="#fff"/><circle cx="220" cy="240" r="30" fill="#e30a0a"/></svg>',
  FI: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#fff"/><rect x="213" width="54" height="480" fill="#003897"/><rect y="213" width="640" height="54" fill="#003897"/></svg>',
  FR: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="213" height="480" fill="#002395"/><rect x="213" width="214" height="480" fill="#fff"/><rect x="427" width="213" height="480" fill="#ef4135"/></svg>',
  NL: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="160" fill="#ae1c28"/><rect y="160" width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#21468b"/></svg>',
  USA: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#b22234"/><rect width="640" height="80" fill="#fff"/><rect width="640" height="80" y="400" fill="#fff"/><rect width="640" height="80" y="80" fill="#fff"/><rect width="640" height="80" y="320" fill="#fff"/><g fill="#fff"><rect x="0" y="0" width="80" height="80"/><rect x="160" y="0" width="80" height="80"/><rect x="320" y="0" width="80" height="80"/><rect x="480" y="0" width="80" height="80"/><rect x="80" y="80" width="80" height="80"/><rect x="240" y="80" width="80" height="80"/><rect x="400" y="80" width="80" height="80"/><rect x="0" y="160" width="80" height="80"/><rect x="160" y="160" width="80" height="80"/><rect x="320" y="160" width="80" height="80"/><rect x="480" y="160" width="80" height="80"/><rect x="80" y="240" width="80" height="80"/><rect x="240" y="240" width="80" height="80"/><rect x="400" y="240" width="80" height="80"/><rect x="0" y="320" width="80" height="80"/><rect x="160" y="320" width="80" height="80"/><rect x="320" y="320" width="80" height="80"/><rect x="480" y="320" width="80" height="80"/></g></svg>',
  AE: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#00732f"/><rect y="160" width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#000"/><rect width="160" height="480" fill="#ce1126"/></svg>',
  RU: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="160" fill="#fff"/><rect y="160" width="640" height="160" fill="#0039a6"/><rect y="320" width="640" height="160" fill="#d52b1e"/></svg>',
  GB: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#012169"/><path d="M0 0L640 480M640 0L0 480" stroke="#fff" stroke-width="40"/><path d="M320 0v480M0 240h640" stroke="#fff" stroke-width="20"/><path d="M0 0l240 240M0 240l240 0M400 0l240 240M400 240l240 0" stroke="#c8102e" stroke-width="20"/></svg>',
  CA: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#ff0000"/><rect width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#fff"/><rect x="240" y="160" width="160" height="160" fill="#ff0000"/><circle cx="320" cy="240" r="40" fill="#fff"/></svg>',
  SG: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#ed2939"/><rect width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#fff"/><circle cx="320" cy="240" r="40" fill="#000"/><circle cx="320" cy="240" r="20" fill="#fff"/></svg>',
  JP: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#fff"/><circle cx="320" cy="240" r="80" fill="#bc002d"/></svg>',
};

const FlagIcon = ({ code }) => (
  <span className="flag-icon" dangerouslySetInnerHTML={{ __html: FLAG_SVGS[code] || FLAG_SVGS.DE }} />
);

const COUNTRY_ALIASES = {
  FL: 'FI',
  UK: 'GB',
  US: 'USA',
  UNITEDSTATES: 'USA',
  UAE: 'AE',
  UNITEDARABEMIRATES: 'AE',
};

const normalizeCountryCode = (node) => {
  const sources = [node.country_code, node.country, node.location, node.name]
    .filter(Boolean)
    .map((value) => String(value).trim().toUpperCase());

  for (const source of sources) {
    const compact = source.replace(/[^A-Z]/g, '');
    const alias = COUNTRY_ALIASES[compact] || compact;
    if (CODES[alias]) return alias;
    const match = Object.entries(CODES).find(([, entry]) => compact === entry.name.replace(/[^A-Z]/g, '').toUpperCase() || compact.includes(entry.name.replace(/[^A-Z]/g, '').toUpperCase()));
    if (match) return match[0];
    const codeMatch = source.match(/\b[A-Z]{2,3}\b/);
    if (codeMatch && CODES[COUNTRY_ALIASES[codeMatch[0]] || codeMatch[0]]) return COUNTRY_ALIASES[codeMatch[0]] || codeMatch[0];
  }
  return null;
};

const nodeMeta = (node) => {
  const latitude = Number(node.latitude);
  const longitude = Number(node.longitude);
  const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude)
    && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
    && !(latitude === 0 && longitude === 0);
  const code = normalizeCountryCode(node);
  const entry = code ? CODES[code] : null;

  return {
    name: entry?.name || (node.country_code ? String(node.country_code).toUpperCase() : 'Location unavailable'),
    flagCode: code,
    coords: hasCoordinates ? [longitude, latitude] : (entry?.coords || null),
    approximate: !hasCoordinates && Boolean(entry?.coords),
  };
};

/* eslint-disable-next-line no-unused-vars */
const Panel = ({ title, tone = 'orange', icon: Icon, tip, className = '', children }) => (
  <section className={`ops-panel ${tone === 'cyan' ? 'cyan' : ''} ${className}`} data-tone={tone || 'orange'}>
    <header>
      <h3><Icon style={{ verticalAlign: -3, marginRight: 8 }} />{title}</h3>
      {tip && <span className="has-tip panel-tip" data-tip={tip} aria-label={tip} role="img" />}
    </header>
    <div className="ops-panel-body">{children}</div>
  </section>
);

const Skeleton = ({ lines = 3 }) => (
  <PanelSkeleton lines={lines} label="Loading" />
);

const StatCell = ({ label, value, tip, tone, spark }) => (
  <div className="ops-stat-cell has-tip" data-tip={tip || ''} role="group" aria-label={label}>
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
    <svg className="mini-line" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="sparkline">
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
  const clamp = (z) => Math.max(1, Math.min(4, z));
  return (
    <div className="map-zoom-wrap">
      <div className="map-zoom-controls" role="group" aria-label="Map zoom controls">
        <button type="button" className="map-zoom-btn" onClick={() => setZoom((z) => clamp(z + 0.25))} aria-label="Zoom in">+
        </button>
        <span className="map-zoom-level" aria-live="polite">{zoom.toFixed(2)}×</span>
        <button type="button" className="map-zoom-btn" onClick={() => setZoom((z) => clamp(z - 0.25))} aria-label="Zoom out">−
        </button>
        {zoom !== 1 && <button type="button" className="map-zoom-btn map-zoom-reset" onClick={() => setZoom(1)} aria-label="Reset zoom">⤢
        </button>}
      </div>
      <div className="map-zoom-viewport" style={{ overflow: zoom > 1 ? 'auto' : 'hidden' }}>
        <div className="map-zoom-canvas" style={{ width: `${100 * zoom}%`, minWidth: '100%' }}>
          <svg className="world-map-real" viewBox="0 0 668 334" preserveAspectRatio="xMidYMid meet"
            style={{ width: '100%', height: 'auto' }}
          role="img" aria-label="World map of node locations"
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
              tabIndex={-1}
              aria-label={feat.properties.name}
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
            const projected = m.coords ? projection(m.coords) : null;
            if (!projected) return null;
            const [x, y] = projected;
            const st = nodeStatus[node.id] || {};
            const online = node.status && (st.reachable === true || (st.reachable === undefined && st.session_diagnostics?.live_count != null && st.node_info !== undefined));
            return (
              <g key={node.id} className="map-marker" transform={`translate(${x},${y})`} aria-label={`${node.name} — ${online ? 'online' : 'offline'}`}>
                {online && <circle className="pulse" r={6} aria-hidden="true" />}
                <circle r={online ? 5 : 3.5} className={online ? 'node-online' : 'node-offline'} aria-hidden="true" />
                <text x={7} y={4} className="node-country-label">{node.name}{m.approximate ? ' · approx.' : ''}</text>
              </g>
            );
          })}
          </svg>
        </div>
      </div>
    </div>
  );
};

const SecurityScoreRing = ({ score }) => {
  const r = 34; const c = 2 * Math.PI * r;
  const off = c - (score / 100) * c;
  const color = score >= 85 ? '#2ff0d4' : score >= 65 ? '#ffb454' : '#ff7a8a';
  return (
    <svg className="score-ring" width="92" height="92" viewBox="0 0 92 92" role="img" aria-label={`Security score ${score} out of 100`}>
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
    const reachable = st.reachable !== undefined
      ? st.reachable
      : st.session_diagnostics !== undefined && st.node_info !== undefined;
    if (!reachable) {
      out.push({ id: `node-${n.id}`, level: 'danger', title: `Node ${n.name} unreachable`, detail: 'No API response from OVNode', action: null });
    }
  });
  (users || []).forEach((u) => {
    if (Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins)) {
      out.push({ id: `full-${u.uuid}`, level: 'warning', title: `User ${u.name} at max logins`, detail: `${u.active_connections}/${u.max_logins} sessions`, action: null });
    }
  });
  const sec = security || {};
  if (Number(sec.auth_errors || 0) > 0) out.push({ id: 'auth', level: 'danger', title: `${sec.auth_errors} auth errors (8h)`, detail: 'Failed authentications across nodes', action: null });
  if (Number(sec.rejects || 0) > 0) out.push({ id: 'rej', level: 'warning', title: `${sec.rejects} connection rejects (8h)`, detail: 'OVNode connection rejects', action: null });
  if (Number(sec.stale_markers || 0) > 0) out.push({ id: 'stale', level: 'warning', title: `${sec.stale_markers} stale session markers`, detail: 'Review stale sessions in Security settings', action: null });
  return out;
};

const ServerStats = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState(null);
  const [nodes, setNodes] = useState(null);
  const [nodeStatus, setNodeStatus] = useState({});
  const [security, setSecurity] = useState(null);
  const [trafficHistory, setTrafficHistory] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    let nodesData = [];
    try {
      const [statsRes, usersRes, nodesRes, metricsRes, secRes] = await Promise.all([
        apiClient.get('/server/info'),
        apiClient.get('/users/'),
        apiClient.get('/nodes/'),
        apiClient.get("/metrics/history?hours=24"),
        apiClient.get('/security/summary?hours=8'),
      ]);
      setStats(statsRes.data?.data || null);
      const usersData = usersRes.data?.data;
      setUsers(Array.isArray(usersData) ? usersData : usersData?.users || []);
      const nodesDataRaw = nodesRes.data?.data;
      nodesData = Array.isArray(nodesDataRaw) ? nodesDataRaw : nodesDataRaw?.nodes || [];
      setNodes(nodesData);
      const secData = secRes.data?.data;
      setSecurity(secData || {});
      const lastTraffic = (metricsRes.data?.data?.traffic || []).at(-1);
      const point = Number(lastTraffic?.active_connections ?? 0);
      setTrafficHistory((h) => [...h.slice(-19), point]);
      setLastUpdated(new Date());
    } catch (e) {
      console.error('Dashboard load failed:', e);
      setError(e);
    }

    // node status: per-node, non-blocking, short timeout
    try {
      const ns = nodesData;
      const results = await Promise.all(ns.map(async (n) => {
        if (!n.status) return [n.id, { status: 'inactive', session_diagnostics: {}, node_info: {}, latency_ms: 0 }];
        try {
          const r = await apiClient.get(`/nodes/${n.id}/status/`, { timeout: 4000 });
          return [n.id, r.data?.data || {}];
        } catch { return [n.id, { status: 'unreachable', session_diagnostics: undefined, node_info: undefined, latency_ms: 0 }]; }
      }));
      setNodeStatus(Object.fromEntries(results));
    } catch { /* keep previous */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') loadData(); }, 30000);
    return () => clearInterval(timer);
  }, [loadData]);

  const onlineNodes = (nodes || []).filter((n) => {
    if (!n.status) return false;
    const st = nodeStatus[n.id] || {};
    return st.reachable === true || (st.reachable === undefined && st.node_info !== undefined && st.session_diagnostics !== undefined);
  }).length;
  const activeConnections = Object.values(nodeStatus).reduce((sum, status) => sum + Number(status?.session_diagnostics?.live_count || 0), 0);
  const avgLatency = (() => {
    const values = Object.values(nodeStatus).map((s) => Number(s?.latency_ms)).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
  })();
  const totalUsed = (users || []).reduce((sum, u) => sum + Number(u.used || 0), 0);
  const activeNodeCount = (nodes || []).filter((node) => node.status).length;
  const offlineNodes = Math.max(0, activeNodeCount - onlineNodes);
  const fullUsers = (users || []).filter((u) => Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins || 0));

  const sec = security || {};
  const authErrors = Number(sec.auth_errors || 0);
  const rejects = Number(sec.rejects || 0);
  const stale = Number(sec.stale_markers || 0);
  const penalty = offlineNodes * 8 + fullUsers.length * 3 + Math.min(authErrors, 50) * 0.6 + Math.min(rejects, 50) * 0.4 + Math.min(stale, 50) * 0.4;
  const securityScore = Math.max(0, Math.min(100, Math.round(100 - penalty)));
  const notifications = deriveNotifications({ users, nodes, nodeStatus, security });
  const activeAlerts = notifications.length;
  const previewUsers = (users || [])
    .filter((u) => Number(u.active_connections || 0) > 0)
    .sort((a, b) => Number(b.active_connections || 0) - Number(a.active_connections || 0))
    .slice(0, 6);

  const hasData = stats && users && nodes;

  return (
    <div className="ops-dashboard compact">
      <div className="dashboard-heading">
        <div className="dashboard-heading-copy">
          <div className="dashboard-eyebrow">
            <span className="live-indicator" aria-hidden="true" />
            <span>{t('liveOperations', 'Live operations')}</span>
            <span className="dashboard-heading-separator" aria-hidden="true">·</span>
            <span className="dashboard-updated" aria-live="polite">
              {lastUpdated ? `${t('updatedAt', 'Updated')} ${lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : t('syncing', 'Syncing data…')}
            </span>
          </div>
          <h1>{t('operationalOverview')}</h1>
          <p>{t('dashboardIntro', 'Keep an eye on nodes, users, traffic, and security from one place.')}</p>
        </div>
        <div className="dashboard-heading-actions">
          <button type="button" className="btn btn-secondary dashboard-refresh" onClick={loadData} disabled={loading}>
            <FiRefreshCw className={loading ? 'is-spinning' : ''} aria-hidden="true" />
            <span>{t('refresh', 'Refresh')}</span>
          </button>
        </div>
      </div>

      {error && !hasData ? (
        <div className="ops-error-wrap">
          <ErrorState
            title={t('loadFailedTitle')}
            message={t('loadFailedMessage')}
            onRetry={loadData}
            retryLabel={t('retry')}
          />
        </div>
      ) : (
        <>
          <div className="ops-overview-grid">
            <Panel title={t('networkStatus')} tone="orange" icon={FiActivity} tip={t('networkStatus')}>
              {loading ? <Skeleton /> : (stats && users && nodes ? (
                <div className="network-card-grid">
                  <StatCell label={t('activeConnections')} value={activeConnections.toLocaleString()} tip={t('activeConnections')} spark={trafficHistory} />
                  <StatCell label={t('totalTraffic')} value={formatBytes(totalUsed)} tip={t('totalTraffic')} spark={trafficHistory.map((v) => v * 8)} />
                  <StatCell label={t('onlineNodes')} value={`${onlineNodes}/${nodes.length || 0}`} tip={t('onlineNodes')} tone={offlineNodes ? 'warn' : 'ok'} />
                  <StatCell label={t('avgLatency')} value={avgLatency ? `${avgLatency.toFixed(0)}ms` : '-'} tip={t('avgLatency')} />
                </div>
              ) : (
                <EmptyState title={t('noData')} description={t('noDataDesc')} />
              ))}
            </Panel>

            <Panel title={t('serverHealth')} tone="cyan" icon={FiServer} tip={t('serverHealth')}>
              {loading ? <Skeleton /> : (stats ? (
                <div className="health-grid">
                  <StatCell label={t('panelCPU')} value={`${stats.cpu.toFixed(0)}%`} tip={t('panelCPU')} tone={stats.cpu > 85 ? 'danger' : stats.cpu > 70 ? 'warn' : 'ok'} />
                  <StatCell label={t('panelMemory')} value={`${stats.memory_percent.toFixed(0)}%`} tip={t('panelMemory')} tone={stats.memory_percent > 85 ? 'danger' : stats.memory_percent > 70 ? 'warn' : 'ok'} />
                  <StatCell label={t('disk')} value={`${stats.disk_percent.toFixed(0)}%`} tip={t('disk')} tone={stats.disk_percent > 85 ? 'danger' : 'ok'} />
                  <StatCell label={t('nodesOnline')} value={`${onlineNodes}/${nodes?.length || 0}`} tip={t('nodesOnline')} tone={offlineNodes ? 'warn' : 'ok'} />
                </div>
              ) : (
                <EmptyState title={t('noData')} description={t('noDataDesc')} />
              ))}
            </Panel>

            <Panel title={t('securityOverview')} tone="orange" className="security-panel" icon={FiShield} tip={t('securityOverview')}>
              {loading ? <Skeleton lines={4} /> : (security ? (
                <div className="security-overview-content">
                  <div className="security-posture">
                    <div className="security-score-block">
                      <SecurityScoreRing score={securityScore} />
                      <div>
                        <span className="security-kicker">{t('securityPosture', 'Security posture')}</span>
                        <strong className={`security-state ${securityScore >= 85 ? 'ok' : securityScore >= 65 ? 'warn' : 'bad'}`}>
                          {securityScore >= 85 ? t('postureHealthy', 'Healthy') : securityScore >= 65 ? t('postureWatch', 'Needs attention') : t('postureCritical', 'Critical')}
                        </strong>
                        <p>{securityScore >= 85 ? t('verdictHealthy') : securityScore >= 65 ? t('verdictWatch') : t('verdictCritical')}</p>
                      </div>
                    </div>
                    <div className="security-metric-grid">
                      <div className="security-metric"><span>{t('activeAlerts')}</span><strong className={activeAlerts ? 'warn' : 'ok'}>{activeAlerts}</strong></div>
                      <div className="security-metric"><span>{t('authErrors8h')}</span><strong className={authErrors ? 'danger' : 'ok'}>{authErrors}</strong></div>
                      <div className="security-metric"><span>{t('rejects8h')}</span><strong className={rejects ? 'warn' : 'ok'}>{rejects}</strong></div>
                      <div className="security-metric"><span>{t('staleMarkers', 'Stale markers')}</span><strong className={stale ? 'warn' : 'ok'}>{stale}</strong></div>
                    </div>
                  </div>
                  <div className="security-review-row">
                    <div className="security-review-list">
                      {notifications.length > 0 ? notifications.slice(0, 2).map((item) => (
                        <div key={item.id} className={`security-review-item ${item.level}`}>
                          <span className="security-review-dot" />
                          <span><strong>{item.title}</strong><small>{item.detail}</small></span>
                        </div>
                      )) : (
                        <div className="security-review-item clear">
                          <FiCheckCircle aria-hidden="true" />
                          <span><strong>{t('securityClear', 'No active security issues')}</strong><small>{t('securityClearDetail', 'Authentication and node checks look normal.')}</small></span>
                        </div>
                      )}
                    </div>
                    <button type="button" className="security-review-button" onClick={() => navigate('/settings#security')}>
                      {t('reviewSecurity', 'Review')}
                      <FiArrowRight aria-hidden="true" />
                    </button>
                  </div>
                </div>
              ) : (
                <EmptyState title={t('noData')} description={t('noDataDesc')} />
              ))}
            </Panel>
          </div>

          <div className="ops-lower-grid">
            <Panel title={t('onlineUsers')} tone="orange" className="users-panel" icon={FiUsers} tip={t('onlineUsers')}>
              {loading ? <Skeleton /> : (users ? (
                <>
                  {previewUsers.length > 0 ? (
                    <table className="ops-table">
                      <thead>
                        <tr><th>{t('th_user')}</th><th>{t('th_plan')}</th><th>{t('th_status')}</th><th>{t('th_dataUsed')}</th><th>{t('th_sessions')}</th><th>{t('th_lastOnline')}</th><th>{t('th_actions')}</th></tr>
                      </thead>
                      <tbody>
                        {previewUsers.map((u) => (
                          <tr key={u.uuid || u.name} title={`${u.name}: ${u.active_connections || 0}/${u.max_logins || '∞'} sessions, ${formatBytes(u.used || 0)} used`}>
                            <td><span className="avatar-mini" aria-hidden="true">{u.name.slice(0, 1).toUpperCase()}</span>{u.name}</td>
                            <td>{u.max_logins === 0 ? t('unlimited') : t('devicesCount', { count: u.max_logins })}</td>
                            <td>
                              <StatusBadge status={u.online ? 'online' : 'idle'} label={u.online ? t('statusOnline') : t('statusOffline')} />
                            </td>
                            <td>{formatBytes(u.used || 0)}</td>
                            <td>{u.active_connections || 0}</td>
                            <td className="col-last-online">{u.online ? t('statusOnline') : fmtRelative(u.last_online)}</td>
                            <td>
                              <button
                                type="button"
                                className="mini-btn"
                                title={`${t('manage')} ${u.name}`}
                                aria-label={`${t('manage')} ${u.name}`}
                                onClick={() => { const base = import.meta.env.VITE_URLPATH ? `/${import.meta.env.VITE_URLPATH}` : ''; window.location.assign(`${base}/users?user=${u.uuid}`); }}
                              >{t('manage')}</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <EmptyState 
                      title={t('noUsersOnline')} 
                      description={t('noUsersOnlineDesc')} 
                      actionLabel={t('addUser', 'Add User')}
                      onAction={() => navigate('/users')}
                    />
                  )}
                </>
              ) : (
                <EmptyState title={t('noData')} description={t('noDataDesc')} />
              ))}
            </Panel>

            <Panel title={t('nodeMap')} tone="cyan" className="nodes-map-panel" icon={FiGlobe} tip={t('nodeMapTip')}>
              {loading ? <Skeleton /> : (nodes ? (
                <>
                  {nodes.length > 0 ? (
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
                            const reachable = node.status && (status.reachable === true || (status.reachable === undefined && status.node_info !== undefined));
                            return (
                              <tr key={node.id} title={`${node.name}: ${conns} live sessions, API ${node.address}:${node.port}`}>
                                <td>{node.name}</td>
                                <td className="node-location-cell">
                                  {meta.flagCode && <FlagIcon code={meta.flagCode} />}
                                  <span>{meta.name}</span>
                                  {meta.approximate && <small>{t('approximate', 'Approx.')}</small>}
                                </td>
                                <td>
                                  <StatusBadge
                                    status={reachable ? 'online' : node.status ? 'warning' : 'offline'}
                                    label={reachable ? t('statusOnline') : (node.status ? t('statusDown') : t('statusOff'))}
                                  />
                                </td>
                                <td>{Number.isFinite(Number(cpu)) ? `${Number(cpu).toFixed(0)}%` : '-'}</td>
                                <td>{conns} <small className="latency-note">{status.latency_ms ? `${status.latency_ms}ms` : ''}</small></td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </>
                  ) : (
                  <EmptyState 
                    title={t('noNodes')} 
                    description={t('noNodesDesc')} 
                    icon={FiGlobe}
                    actionLabel={t('addNode', 'Add Node')}
                    onAction={() => navigate('/nodes')}
                  />
                )}
                </>
              ) : (
                <EmptyState title={t('noData')} description={t('noDataDesc')} />
              ))}
            </Panel>
          </div>

          <section className={`ops-alert-center ${notifications.length > 0 ? 'has-alerts' : 'is-clear'}`} aria-live="polite" aria-labelledby="alert-center-title">
            <div className="alert-center-header">
              <div className="alert-center-heading">
                <span className="alert-center-icon" aria-hidden="true">
                  {notifications.length > 0 ? <FiAlertTriangle /> : <FiCheckCircle />}
                </span>
                <div>
                  <h3 id="alert-center-title">{notifications.length > 0 ? t('attentionRequired', 'Attention required') : t('allSystemsClear', 'All systems clear')}</h3>
                  <p>{notifications.length > 0
                    ? `${notifications.length} ${t(notifications.length === 1 ? 'alertOne' : 'alertsMany')} need review.`
                    : t('allSystemsClearDetail', 'No active node, session, or authentication alerts.')}</p>
                </div>
              </div>
              <button type="button" className="alert-center-action" onClick={() => navigate('/settings#security')}>
                {t('reviewSecurity', 'Review security')} <FiArrowRight aria-hidden="true" />
              </button>
            </div>
            {notifications.length > 0 ? (
              <div className="alert-center-list">
                {notifications.slice(0, 4).map((n) => (
                  <div key={n.id} className={`alert-center-item ${n.level}`}>
                    <span className="alert-center-item-dot" aria-hidden="true" />
                    <span className="alert-center-item-copy"><strong>{n.title}</strong><small>{n.detail}</small></span>
                    <span className="alert-center-severity">{n.level === 'danger' ? t('critical', 'Critical') : t('warning', 'Warning')}</span>
                  </div>
                ))}
                {notifications.length > 4 && <span className="alert-center-more">{t('moreN', { count: notifications.length - 4 })}</span>}
              </div>
            ) : (
              <div className="alert-center-clear-state">
                <FiCheckCircle aria-hidden="true" />
                <span>{t('monitoringNormally', 'Monitoring is running normally. We will surface issues here.')}</span>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};

export default ServerStats;
