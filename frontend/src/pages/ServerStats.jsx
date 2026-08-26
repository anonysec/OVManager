import { useState, useEffect, useMemo, useCallback, useRef, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { FiShield, FiActivity, FiServer, FiUsers, FiGlobe, FiAlertTriangle, FiCheckCircle, FiRefreshCw, FiArrowRight } from 'react-icons/fi';
import { fmtRelative } from '../utils/time';
import { readPrefs, alertPrefKey } from '../utils/notifPrefs';
import { nodeMeta } from '../utils/geo.js';
import FlagIcon from '../utils/geo.jsx';
import { getPanelBase } from '../utils/panelUrl';
import { useCountUp } from '../hooks/useCountUp';
import { usePullRefresh } from '../hooks/usePullRefresh';
import { settle } from '../hooks/useAsyncData';
import { FiPlus, FiDownloadCloud, FiLink } from 'react-icons/fi';
import { ErrorState, EmptyState, PanelSkeleton, StatusBadge } from '../components/ui';
import SectionBoundary from '../components/ui/SectionBoundary';
import { SkeletonStats, SkeletonPanel } from '../components/ui/Skeleton';

// The atlas carries d3-geo + topojson + a 105 kB TopoJSON file. Loading it
// lazily keeps them out of the dashboard's critical path — the KPI cards and
// tables above it render immediately and the map streams in underneath.
const WorldMap = lazy(() => import('../components/dashboard/WorldMap'));

const formatBytes = (bytes) => {
  if (!Number(bytes)) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(1)} ${u[i]}`
};

const Panel = ({ title, tone = 'orange', icon: Icon, tip, className = '', children }) => (
  <section className={`ops-panel ${tone === 'cyan' ? 'cyan' : ''} ${className}`} data-tone={tone || 'orange'}>
    <header>
      <h3><Icon style={{ verticalAlign: -3, marginRight: 8 }} />{title}</h3>
      {tip && <span className="has-tip panel-tip" data-tip={tip} aria-label={tip} role="img" />}
    </header>
    <div className="ops-panel-body">{children}</div>
  </section>
);

/**
 * Resolves one panel's body to exactly one of: skeleton / inline error / empty
 * / content — in that order.
 *
 * Centralising this is what makes per-section error handling practical: each
 * panel passes its own slice of the error map and gets a scoped retry, so a
 * dead endpoint costs one card instead of the page. Keeping stale content
 * visible on a *refresh* failure (rather than replacing it with an error) is
 * deliberate — old numbers plus a warning beat no numbers at all.
 */
const PanelState = ({ loading, error, isEmpty, onRetry, skeleton, children, t }) => {
  if (loading) return skeleton ?? <PanelSkeleton lines={3} label={t('loading', 'Loading…')} />;

  if (error) {
    return (
      <div className="panel-inline-error" role="alert">
        <FiAlertTriangle aria-hidden="true" />
        <div>
          <strong>{t('panelLoadFailed', 'Could not load this panel')}</strong>
          <span>{t('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
        </div>
        {onRetry && (
          <button type="button" className="btn btn-sm btn-secondary" onClick={onRetry}>
            <FiRefreshCw size={12} aria-hidden="true" /> {t('retry', 'Retry')}
          </button>
        )}
      </div>
    );
  }

  if (isEmpty) return <EmptyState title={t('noData')} description={t('noDataDesc')} />;
  return children;
};

const Skeleton = ({ lines = 3 }) => (
  <PanelSkeleton lines={lines} label="Loading" />
);

const StatCell = ({ label, value, tip, tone, spark, animate, format }) => {
  const raw = animate && format ? animate : null;
  const anim = useCountUp(raw || 0);
  const display = animate
    ? format
      ? format(anim)
      : Math.round(anim).toLocaleString()
    : value;
  return (
    <div className="ops-stat-cell has-tip" data-tip={tip || ''} role="group" aria-label={label}>
      <span>{label}</span>
      <strong className={`${tone === 'danger' ? 'tone-danger' : tone === 'warn' ? 'tone-warn' : tone === 'ok' ? 'tone-ok' : ''} count-up-num`}>{display}</strong>
      {spark && spark.length > 1 && <MiniLine values={spark} />}
    </div>
  );
};

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


const SecurityScoreRing = ({ score }) => {
  const r = 34; const c = 2 * Math.PI * r;
  const off = c - (score / 100) * c;
  const color = score >= 85 ? '#2ff0d4' : score >= 65 ? '#ffb454' : '#ff7a8a';
  return (
    <svg className="score-ring" width="92" height="92" viewBox="0 0 92 92" role="img" aria-label={`Security score ${score} out of 100`}>
      <circle cx="46" cy="46" r={r} className="ring-bg" />
      <circle cx="46" cy="46" r={r} className="ring-fg" stroke={color}
        strokeDasharray={c} strokeDashoffset={off} transform="rotate(-90 46 46)" />
      <text x="46" y="46" className="ring-num" fill={color} textAnchor="middle" dominantBaseline="central">{score}</text>
    </svg>
  );
};

const deriveNotifications = ({ users, nodes, nodeStatus, security, t }) => {
  const out = [];
  (nodes || []).forEach((n) => {
    if (!n.status) return; // DB-inactive nodes aren't "down"
    const st = nodeStatus?.[n.id] || {};
    const reachable = st.reachable !== undefined
      ? st.reachable
      : st.session_diagnostics !== undefined && st.node_info !== undefined;
    if (!reachable) {
      out.push({ id: `node-${n.id}`, level: 'danger', title: t('notifNodeUnreachable', 'Node {{name}} unreachable', { name: n.name }), detail: t('notifNodeUnreachableDetail', 'No API response from OVNode'), action: null });
    }
  });
  (users || []).forEach((u) => {
    if (Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins)) {
      out.push({ id: `full-${u.uuid}`, level: 'warning', title: t('notifUserAtMax', 'User {{name}} at max logins', { name: u.name }), detail: t('notifUserAtMaxDetail', '{{active}}/{{max}} sessions', { active: u.active_connections, max: u.max_logins }), action: null });
    }
  });
  const sec = security || {};
  if (Number(sec.auth_errors || 0) > 0) out.push({ id: 'auth', level: 'danger', title: t('notifAuthErrors', '{{count}} auth errors (8h)', { count: sec.auth_errors }), detail: t('notifAuthErrorsDetail', 'Failed authentications across nodes'), action: null });
  if (Number(sec.rejects || 0) > 0) out.push({ id: 'rej', level: 'warning', title: t('notifRejects', '{{count}} connection rejects (8h)', { count: sec.rejects }), detail: t('notifRejectsDetail', 'OVNode connection rejects'), action: null });
  if (Number(sec.stale_markers || 0) > 0) out.push({ id: 'stale', level: 'warning', title: t('notifStale', '{{count}} stale session markers', { count: sec.stale_markers }), detail: t('notifStaleDetail', 'Review stale sessions in Security settings'), action: null });
  // Respect the "Alerts & Dashboard" preferences from Settings.
  const prefs = readPrefs();
  return out.filter((n) => {
    const pref = alertPrefKey(n.id);
    return !pref || prefs[pref] !== false;
  });
};


/* TrafficChart — SVG area chart of total traffic over time.
   Period toggle: 24h / 7d. (Deliberately no TCP/UDP split — the metrics
   snapshot stores aggregate traffic.) */
const TrafficChart = () => {
  const { t } = useTranslation();
  const [period, setPeriod] = useState('24h');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const hours = period === '7d' ? 168 : 24;
    apiClient.get(`/metrics/history?hours=${hours}`)
      .then((r) => { if (!cancelled) setData(r.data?.data?.traffic || []); })
      .catch(() => { if (!cancelled) setData([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [period]);

  const points = useMemo(() => {
    const series = data.map((p) => Number(p.total_used || 0));
    if (!series.length) return [];
    const max = Math.max(...series, 1);
    return series.map((v, i) => ({
      x: (i / (series.length - 1 || 1)) * 100,
      y: 100 - (v / max) * 88 - 6,
      v,
    }));
  }, [data]);

  const peak = useMemo(() => Math.max(0, ...data.map((p) => Number(p.total_used || 0))), [data]);
  const last = Number(data.at(-1)?.total_used || 0);

  return (
    <section className="ops-panel traffic-chart-card">
      <header>
        <h3>{t('trafficChartTitle', 'Traffic')}</h3>
        <div className="chart-toggles" role="group" aria-label={t('trafficChartPeriod', 'Period')}>
          <button type="button" className={period === '24h' ? 'active' : ''} onClick={() => setPeriod('24h')}>24h</button>
          <button type="button" className={period === '7d' ? 'active' : ''} onClick={() => setPeriod('7d')}>7d</button>
        </div>
      </header>
      <div className="ops-panel-body">
        {loading && data.length === 0 ? (
          <div className="chart-empty">{t('loading', 'Loading…')}</div>
        ) : points.length > 1 ? (
          <>
            <svg viewBox="0 0 100 110" preserveAspectRatio="none" role="img" aria-label={t('trafficChartTitle', 'Traffic')}>
              <defs>
                <linearGradient id="trafficAreaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="var(--cyan)" stopOpacity=".32" />
                  <stop offset="1" stopColor="var(--cyan)" stopOpacity="0" />
                </linearGradient>
              </defs>
              {[22, 44, 66, 88].map((y) => <line key={y} className="chart-grid" x1="0" y1={y} x2="100" y2={y} />)}
              <path className="chart-area" d={`M0,110 L${points.map((p) => `${p.x},${p.y}`).join(' L')} L100,110 Z`} />
              <path className="chart-line" d={`M${points.map((p) => `${p.x},${p.y}`).join(' L')}`} vectorEffect="non-scaling-stroke" />
            </svg>
            <div className="chart-summary">
              <div><b>{formatBytes(last)}</b><span>{t('trafficNow', 'Current')}</span></div>
              <div><b>{formatBytes(peak)}</b><span>{t('trafficPeak', 'Peak')}</span></div>
              <div><b>{period === '7d' ? '7' : '24'}h</b><span>{t('trafficWindow', 'Window')}</span></div>
            </div>
          </>
        ) : (
          <div className="chart-empty">{t('noMetrics', 'No metrics yet.')}</div>
        )}
      </div>
    </section>
  );
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
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Per-source error map. Previously a single `error` flag driven by one
  // Promise.all rejection blanked the entire dashboard whenever ANY of the
  // five endpoints failed — a flaky /security/summary would hide healthy
  // node and user data. Each key now fails on its own.
  const [errors, setErrors] = useState({});

  /**
   * @param background  true for polls/SSE refreshes: keeps current data on
   *                    screen and skips the skeleton so the dashboard never
   *                    flashes empty while the user is reading it.
   */
  const loadData = useCallback(async (background = false) => {
    if (background) setRefreshing(true);
    // Functional update: only show the skeleton when there is nothing on
    // screen yet, without needing to read state during render.
    else setLoading(true);

    // allSettled, not all: one rejection must not discard four good responses.
    const res = await settle({
      stats: apiClient.get('/server/info'),
      users: apiClient.get('/users/'),
      nodes: apiClient.get('/nodes/'),
      metrics: apiClient.get('/metrics/history?hours=24'),
      security: apiClient.get('/security/summary?hours=8'),
    });

    const nextErrors = {};

    if (res.stats.ok) setStats(res.stats.data.data?.data || res.stats.data.data || null);
    else nextErrors.stats = res.stats.error;

    if (res.users.ok) {
      setUsers(asList(res.users.data, 'users'));
    } else nextErrors.users = res.users.error;

    let nodesData = [];
    if (res.nodes.ok) {
      nodesData = asList(res.nodes.data, 'nodes');
      setNodes(nodesData);
    } else {
      nextErrors.nodes = res.nodes.error;
    }

    if (res.security.ok) setSecurity(res.security.data.data?.data || {});
    else nextErrors.security = res.security.error;

    if (res.metrics.ok) {
      const lastTraffic = (res.metrics.data.data?.data?.traffic || []).at(-1);
      setTrafficHistory((h) => [...h.slice(-19), Number(lastTraffic?.active_connections ?? 0)]);
    } else nextErrors.metrics = res.metrics.error;

    setErrors(nextErrors);
    setLastUpdated(new Date());
    // Release the skeleton as soon as the core payload is in — the per-node
    // probes below can take seconds and shouldn't hold up first paint.
    setLoading(false);

    // Per-node status: already fault-isolated per node, and intentionally
    // awaited after the main render so slow/unreachable nodes never delay it.
    try {
      const results = await Promise.all(nodesData.map(async (n) => {
        if (!n.status) return [n.id, { status: 'inactive', session_diagnostics: {}, node_info: {}, latency_ms: 0 }];
        try {
          const r = await apiClient.get(`/nodes/${n.id}/status/`, { timeout: 4000 });
          return [n.id, r.data?.data || {}];
        } catch { return [n.id, { status: 'unreachable', session_diagnostics: undefined, node_info: undefined, latency_ms: 0 }]; }
      }));
      setNodeStatus(Object.fromEntries(results));
    } catch { /* keep previous */ }

    setRefreshing(false);
  }, []);

  // Poll cadence comes from Settings → Alerts & Dashboard, and restarts
  // immediately when the preference changes.
  useEffect(() => {
    // First load shows skeletons; every subsequent tick is a *background*
    // refresh that leaves the current numbers on screen. This is what stops
    // the dashboard blinking back to skeletons every 30 seconds.
    loadData(false);
    let id = null;
    const start = (immediate = false) => {
      if (id) clearInterval(id);
      if (immediate) loadData(true);
      const sec = readPrefs().refreshSec;
      id = setInterval(() => { if (document.visibilityState === 'visible') loadData(true); }, sec * 1000);
    };
    start();
    const onPrefs = () => start(true);
    window.addEventListener('ovmanager-prefs-changed', onPrefs);
    return () => { if (id) clearInterval(id); window.removeEventListener('ovmanager-prefs-changed', onPrefs); };
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
  const notifications = deriveNotifications({ users, nodes, nodeStatus, security, t });
  const activeAlerts = notifications.length;
  const previewUsers = (users || [])
    .filter((u) => Number(u.active_connections || 0) > 0)
    .sort((a, b) => Number(b.active_connections || 0) - Number(a.active_connections || 0))
    .slice(0, 6);

  // Only fall back to the whole-page error state when literally nothing
  // resolved. Any partial success renders the page with per-panel errors.
  const allFailed = !loading
    && Boolean(errors.stats && errors.users && errors.nodes && errors.security && errors.metrics);

  // Pull-to-refresh (touch) + condensed mobile KPI
  const dashRef = useRef(null);
  const pull = usePullRefresh(() => { window.dispatchEvent(new Event('ovmanager:loading')); return loadData(true); });
  const mobileKpi = [
    { label: t('activeConnections'), value: activeConnections.toLocaleString() },
    { label: t('onlineNodes'), value: `${onlineNodes}/${nodes?.length || 0}` },
    { label: t('totalTraffic'), value: formatBytes(totalUsed) },
    { label: t('avgLatency'), value: avgLatency ? `${avgLatency.toFixed(0)}ms` : '-' },
  ];

  return (
    <div
      className="ops-dashboard compact"
      ref={dashRef}
      onTouchStart={pull.onTouchStart}
      onTouchMove={pull.onTouchMove}
      onTouchEnd={pull.onTouchEnd}
    >
      <div className={`pull-refresh-indicator${pull.refreshing ? ' refreshing' : pull.pull > 0 ? ' pulling' : ''}`}>
        {pull.refreshing ? <span className="spinner" /> : <span>⬇ {t('pullToRefresh', 'Pull to refresh')}</span>}
      </div>
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
          <button type="button" className="btn btn-secondary dashboard-refresh" onClick={() => { window.dispatchEvent(new Event('ovmanager:loading')); loadData(true); }} disabled={loading || refreshing}>
            <FiRefreshCw className={loading || refreshing ? 'is-spinning' : ''} aria-hidden="true" />
            <span>{t('refresh', 'Refresh')}</span>
          </button>
        </div>
        <div className="dashboard-quick-actions">
          <button type="button" className="btn btn-sm" onClick={() => navigate('/users?add=1')}><FiPlus size={12} /> {t('addUser', 'Add user')}</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate('/nodes?add=1')}><FiPlus size={12} /> {t('addNode', 'Add node')}</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate('/nodes')}><FiDownloadCloud size={12} /> {t('downloadAll', 'Download all')}</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate('/users')}><FiLink size={12} /> {t('subscriptions', 'Subscriptions')}</button>
        </div>
      </div>

      <div className="dashboard-kpi-compact">
        {mobileKpi.map((k) => (
          <div key={k.label} className="kpi-box"><span>{k.label}</span><b>{k.value}</b></div>
        ))}
      </div>

      {allFailed ? (
        <div className="ops-error-wrap">
          <ErrorState
            title={t('loadFailedTitle')}
            message={t('loadFailedMessage')}
            onRetry={() => loadData()}
            retryLabel={t('retry')}
          />
        </div>
      ) : (
        <>
          <div className="ops-overview-grid">
            <Panel title={t('networkStatus')} tone="orange" icon={FiActivity} tip={t('networkStatus')}>
              <PanelState
                t={t}
                loading={loading}
                error={errors.stats && errors.users && errors.nodes}
                isEmpty={!stats && !users && !nodes}
                onRetry={() => loadData()}
                skeleton={<SkeletonStats count={4} label={t('loading', 'Loading…')} />}
              >
                <div className="network-card-grid">
                  <StatCell label={t('activeConnections')} value={activeConnections.toLocaleString()} animate={activeConnections} tip={t('activeConnections')} spark={trafficHistory} />
                  <StatCell label={t('totalTraffic')} value={formatBytes(totalUsed)} animate={totalUsed} format={formatBytes} tip={t('totalTraffic')} spark={trafficHistory.map((v) => v * 8)} />
                  <StatCell label={t('onlineNodes')} value={`${onlineNodes}/${nodes?.length || 0}`} tip={t('onlineNodes')} tone={offlineNodes ? 'warn' : 'ok'} />
                  <StatCell label={t('avgLatency')} value={avgLatency ? `${avgLatency.toFixed(0)}ms` : '-'} tip={t('avgLatency')} />
                </div>
              </PanelState>
            </Panel>

            <Panel title={t('serverHealth')} tone="cyan" icon={FiServer} tip={t('serverHealth')}>
              <PanelState
                t={t}
                loading={loading}
                error={errors.stats}
                isEmpty={!stats}
                onRetry={() => loadData()}
                skeleton={<SkeletonStats count={4} label={t('loading', 'Loading…')} />}
              >
                {stats && (
                  <div className="health-grid">
                    <StatCell label={t('panelCPU')} value={`${stats.cpu.toFixed(0)}%`} tip={t('panelCPU')} tone={stats.cpu > 85 ? 'danger' : stats.cpu > 70 ? 'warn' : 'ok'} />
                    <StatCell label={t('panelMemory')} value={`${stats.memory_percent.toFixed(0)}%`} tip={t('panelMemory')} tone={stats.memory_percent > 85 ? 'danger' : stats.memory_percent > 70 ? 'warn' : 'ok'} />
                    <StatCell label={t('disk')} value={`${stats.disk_percent.toFixed(0)}%`} tip={t('disk')} tone={stats.disk_percent > 85 ? 'danger' : 'ok'} />
                    <StatCell label={t('nodesOnline')} value={`${onlineNodes}/${nodes?.length || 0}`} tip={t('nodesOnline')} tone={offlineNodes ? 'warn' : 'ok'} />
                  </div>
                )}
              </PanelState>
            </Panel>

            <Panel title={t('securityOverview')} tone="orange" className="security-panel" icon={FiShield} tip={t('securityOverview')}>
              {loading ? <Skeleton lines={4} /> : errors.security ? (
                <div className="panel-inline-error" role="alert">
                  <FiAlertTriangle aria-hidden="true" />
                  <div>
                    <strong>{t('panelLoadFailed', 'Could not load this panel')}</strong>
                    <span>{t('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
                  </div>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => loadData()}>
                    <FiRefreshCw size={12} aria-hidden="true" /> {t('retry', 'Retry')}
                  </button>
                </div>
              ) : (security ? (
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

          <TrafficChart />

          <div className="ops-lower-grid">
            <Panel title={t('onlineUsers')} tone="orange" className="users-panel" icon={FiUsers} tip={t('onlineUsers')}>
              {loading ? <Skeleton /> : errors.users ? (
                <div className="panel-inline-error" role="alert">
                  <FiAlertTriangle aria-hidden="true" />
                  <div>
                    <strong>{t('panelLoadFailed', 'Could not load this panel')}</strong>
                    <span>{t('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
                  </div>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => loadData()}>
                    <FiRefreshCw size={12} aria-hidden="true" /> {t('retry', 'Retry')}
                  </button>
                </div>
              ) : (users ? (
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
                                onClick={() => { window.location.assign(`${getPanelBase()}/users?user=${u.uuid}`); }}
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
              {loading ? <Skeleton /> : errors.nodes ? (
                <div className="panel-inline-error" role="alert">
                  <FiAlertTriangle aria-hidden="true" />
                  <div>
                    <strong>{t('panelLoadFailed', 'Could not load this panel')}</strong>
                    <span>{t('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
                  </div>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => loadData()}>
                    <FiRefreshCw size={12} aria-hidden="true" /> {t('retry', 'Retry')}
                  </button>
                </div>
              ) : (nodes ? (
                <>
                  {nodes.length > 0 ? (
                    <>
                      {/* The atlas is a separate chunk and its own failure
                          domain: if d3/topojson fail to load, the node table
                          below still renders. */}
                      <SectionBoundary name="world-map" compact title={t('mapUnavailable', 'Map unavailable')}>
                        <Suspense fallback={<SkeletonPanel lines={6} height={300} label={t('loadingMap', 'Loading map…')} />}>
                          <WorldMap nodes={nodes} nodeStatus={nodeStatus} />
                        </Suspense>
                      </SectionBoundary>
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

          {/* Minimal alert strip — one slim row, no big panel. */}
          <section
            className={`ops-alert-center ${notifications.length > 0 ? 'has-alerts' : 'is-clear'}`}
            aria-live="polite"
            aria-label={notifications.length > 0 ? t('attentionRequired', 'Attention required') : t('allSystemsClear', 'All systems clear')}
            title={notifications.map((n) => n.title).join('\n') || t('allSystemsClear', 'All systems clear')}
          >
            <span className="ops-alert-mini-icon" aria-hidden="true">
              {notifications.length > 0 ? <FiAlertTriangle /> : <FiCheckCircle />}
            </span>
            <span className="ops-alert-mini-text">
              {notifications.length > 0
                ? notifications.slice(0, 2).map((n) => n.title).join(' · ')
                : t('allSystemsClear', 'All systems clear')}
            </span>
            {notifications.length > 2 && (
              <span className="ops-alert-mini-more">+{notifications.length - 2}</span>
            )}
            {notifications.length > 0 && (
              <button type="button" className="ops-alert-mini-action" onClick={() => navigate('/settings#security')}>
                {t('reviewSecurity', 'Review')}
              </button>
            )}
          </section>
        </>
      )}
    </div>
  );
};

export default ServerStats;
