// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { FiActivity, FiServer, FiUsers, FiBarChart2, FiPlus, FiArrowRight } from 'react-icons/fi';
import { formatBytes } from '../utils/format';
import { daysUntil, fmtDateTime } from '../utils/time';
import { readPrefs, alertPrefKey } from '../utils/notifPrefs';
import { nodeMeta } from '../utils/geo.js';
import FlagIcon from '../utils/geo.jsx';
import { settle } from '../hooks/useAsyncData';
import { useLive } from '../context/LiveContext';
import { useAuth } from '../context/AuthContext';
import {
  Badge, Button, Card, DataTable, EmptyState, ErrorState, PageHeader, SkeletonTable, StatusBadge, Tabs,
} from '../components/ui';
import KpiCard from '../components/dashboard/KpiCard';
import AlertStrip from '../components/dashboard/AlertStrip';
import ServerHealth from '../components/dashboard/ServerHealth';
import ActivityFeed from '../components/dashboard/ActivityFeed';
import StreamChart from '../components/dashboard/StreamChart';
import './Dashboard.css';

/**
 * Notifications derived from live state — actionable items only.
 * We never flag a node as down before the per-node probe resolves;
 * doing so would flash every node as "unreachable" on first paint
 * and inflate the alert count.
 */
const deriveNotifications = ({ users, nodes, nodeStatus, serverNotifs, probesReady, t }) => {
  const out = [];
  if (probesReady) {
    (nodes || []).forEach((n) => {
      if (!n.status) return;
      const st = nodeStatus?.[n.id] || {};
      const reachable = st.reachable !== undefined
        ? st.reachable
        : st.session_diagnostics !== undefined && st.node_info !== undefined;
      if (!reachable) {
        out.push({ id: `node-${n.id}`, level: 'danger', link: '/nodes', title: t('notifNodeUnreachable', 'Node {{name}} unreachable', { name: n.name }) });
      }
    });
  }
  (serverNotifs || []).forEach((s) => {
    if (!s?.target && !s?.title) return;
    const key = `srv-${s.type || 'info'}-${s.target || s.title}`;
    if (out.some((n) => n.id === key)) return;
    out.push({ id: key, level: s.level || 'warning', link: '/nodes', title: s.title });
  });
  (users || []).forEach((u) => {
    if (Number(u.max_logins || 0) > 0 && Number(u.active_connections || 0) >= Number(u.max_logins)) {
      out.push({ id: `full-${u.uuid}`, level: 'warning', link: `/users?user=${u.uuid}`, title: t('notifUserAtMax', 'User {{name}} at max logins', { name: u.name }) });
    }
    const quota = Number(u.total || 0);
    if (quota > 0) {
      const pct = Number(u.used || 0) / quota;
      if (pct >= 1) {
        out.push({ id: `quota-${u.uuid}`, level: 'danger', link: `/users?user=${u.uuid}`, title: t('notifUserOverQuota', 'User {{name}} over quota', { name: u.name }) });
      } else if (pct >= 0.8) {
        out.push({ id: `quota-${u.uuid}`, level: 'warning', link: `/users?user=${u.uuid}`, title: t('notifUserNearQuota', 'User {{name}} at {{pct}}% of quota', { name: u.name, pct: Math.round(pct * 100) }) });
      }
    }
  });
  const prefs = readPrefs();
  return out.filter((n) => {
    const pref = alertPrefKey(n.id);
    return !pref || prefs[pref] !== false;
  });
};

const userStatusOf = (u) => {
  if (u.online || Number(u.active_connections || 0) > 0) return 'online';
  if (daysUntil(u.expiry_date) < 0) return 'danger';
  if (u.is_active === false) return 'offline';
  return 'idle';
};

const statusLabelFor = (u, t) => {
  const st = userStatusOf(u);
  if (st === 'online') return t('statusOnline', 'Online');
  if (st === 'danger') return t('expired', 'Expired');
  if (st === 'offline') return t('disabled', 'Disabled');
  return t('statusOffline', 'Offline');
};

const fmtUpdated = (date) => {
  if (!date) return '—';
  // Operator display timezone (not browser-local): consistent with every
  // other timestamp in the panel. Seconds kept — this label ticks live.
  return fmtDateTime(date.toISOString(), { second: '2-digit' });
};

// Growth of the cumulative "total_used" counter across the metrics window.
// Usage resets can make a single step negative; those are clamped to zero so
// a reset never shows up as negative traffic.
const sumPositiveDeltas = (values) => {
  const list = (values || []).map(Number).filter(Number.isFinite);
  if (list.length < 2) return null;
  let sum = 0;
  for (let i = 1; i < list.length; i += 1) {
    const delta = list[i] - list[i - 1];
    if (delta > 0) sum += delta;
  }
  return sum;
};

const ServerStats = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  // Normal admins get a scoped dashboard: node list, server info, metrics
  // history and per-node probes are owner-only (backend 403s them).
  const { userRole } = useAuth();
  const isOwner = userRole === 'owner';

  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState(null);
  const [nodes, setNodes] = useState(null);
  const [nodeStatus, setNodeStatus] = useState({});
  const [serverNotifs, setServerNotifs] = useState([]);
  const [activity, setActivity] = useState(null);
  const [trafficSeries, setTrafficSeries] = useState({ conns: [], bytes: [] });
  const [probesDone, setProbesDone] = useState(false);
  const [refreshStale, setRefreshStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(true);

  const [errors, setErrors] = useState({});

  const loadData = useCallback(async (background = false) => {
    if (!background) setLoading(true);

    const res = await settle({
      // Owner-only reads live behind isOwner so admins never 403-spam.
      ...(isOwner ? {
        stats: apiClient.get('/server/info'),
        nodes: apiClient.get('/nodes/'),
        metrics: apiClient.get('/metrics/history?hours=24'),
      } : {}),
      users: apiClient.get('/users/'),
      notifs: apiClient.get('/notifications/'),
      activity: apiClient.get('/activity/?limit=8'),
    });

    const nextErrors = {};

    if (res.stats?.ok) setStats(res.stats.data.data?.data || res.stats.data.data || null);
    else if (res.stats) nextErrors.stats = res.stats.error;

    if (res.users.ok) setUsers(asList(res.users.data, 'users'));
    else nextErrors.users = res.users.error;

    let nodesData = [];
    if (res.nodes?.ok) {
      nodesData = asList(res.nodes.data, 'nodes');
      setNodes(nodesData);
    } else if (res.nodes) nextErrors.nodes = res.nodes.error;

    if (res.metrics?.ok) {
      const series = res.metrics.data.data?.data?.traffic || res.metrics.data.data?.traffic || [];
      setTrafficSeries({
        conns: series.map((p) => Number(p.active_connections || 0)),
        bytes: series.map((p) => Number(p.total_used || 0)),
      });
    } else if (res.metrics) nextErrors.metrics = res.metrics.error;

    if (res.notifs?.ok) {
      const items = res.notifs.data.data?.data ?? res.notifs.data.data ?? [];
      setServerNotifs(Array.isArray(items) ? items : []);
    }

    if (res.activity?.ok) {
      const items = res.activity.data.data?.data ?? res.activity.data.data ?? [];
      setActivity(Array.isArray(items) ? items : []);
    } else {
      nextErrors.activity = res.activity?.error;
      setActivity(null);
    }

    setErrors(nextErrors);
    if (!background || Object.keys(nextErrors).length === 0) {
      setLastUpdated(new Date());
      setRefreshStale(false);
    } else {
      setRefreshStale(true);
    }
    setLoading(false);

    try {
      const results = await Promise.all(nodesData.map(async (n) => {
        if (!n.status) return [n.id, { status: 'inactive', session_diagnostics: {}, node_info: {}, latency_ms: 0, reachable: false }];
        try {
          const r = await apiClient.get(`/nodes/${n.id}/status/`, { timeout: 4000 });
          return [n.id, r.data?.data || {}];
        } catch { return [n.id, { status: 'unreachable', session_diagnostics: undefined, node_info: undefined, latency_ms: 0, reachable: false }]; }
      }));
      setNodeStatus(Object.fromEntries(results));
      setProbesDone(true);
    } catch { /* keep previous */ }
  }, [isOwner]);

  const { subscribe, streamConnected } = useLive();

  useEffect(() => {
    const off = subscribe('tick', () => loadData(true));
    return () => off();
  }, [subscribe, loadData]);

  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      loadData(false);
    }
    if (streamConnected) return undefined;
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
  }, [loadData, streamConnected]);

  const onlineNodes = (nodes || []).filter((n) => {
    if (!n.status) return false;
    const st = nodeStatus[n.id] || {};
    return st.reachable === true || (st.reachable === undefined && st.node_info !== undefined && st.session_diagnostics !== undefined);
  }).length;
  const activeConnections = isOwner
    ? Object.values(nodeStatus).reduce((sum, s) => sum + Number(s?.session_diagnostics?.live_count || 0), 0)
    : (users || []).reduce((sum, u) => sum + Number(u.active_connections || 0), 0);
  const totalUsed = (users || []).reduce((sum, u) => sum + Number(u.used || 0), 0);
  const activeNodeCount = (nodes || []).filter((n) => n.status).length;
  const offlineNodes = probesDone ? Math.max(0, activeNodeCount - onlineNodes) : 0;
  const onlineTotal = (users || []).filter((u) => Number(u.active_connections || 0) > 0).length;
  const activeTotal = (users || []).filter((u) => u.is_active).length;
  const totalUsers = (users || []).length;
  const probesReady = probesDone || (nodes?.length || 0) === 0;
  const probesPending = !probesReady;
  const notifications = deriveNotifications({ users, nodes, nodeStatus, serverNotifs, probesReady, t });

  const trafficToday = useMemo(() => sumPositiveDeltas(trafficSeries.bytes), [trafficSeries.bytes]);

  const attentionUsers = useMemo(() => {
    const rows = [];
    for (const u of users || []) {
      if (!u?.name) continue;
      const reasons = [];
      const d = daysUntil(u.expiry_date);
      if (d >= 0 && d <= 7) reasons.push('expiring');
      if (Number(u.total) > 0 && (Number(u.used || 0) / Number(u.total)) >= 0.85) reasons.push('quota');
      if (!u.is_active) reasons.push('disabled');
      if (reasons.length) rows.push({ user: u, reasons });
    }
    return rows;
  }, [users]);

  const nodeHealthRows = useMemo(() => (nodes || []).map((n) => {
    const st = nodeStatus[n.id] || {};
    const reachable = Boolean(n.status) && (st.reachable === true || (st.reachable === undefined && st.node_info !== undefined));
    return {
      node: n,
      status: !n.status ? 'off' : reachable ? 'online' : 'down',
      live: Number(st.session_diagnostics?.live_count || 0),
      latency: Number(st.latency_ms || 0),
      meta: nodeMeta(n),
    };
  }), [nodes, nodeStatus]);

  const attentionReasonLabel = useCallback((reason) => {
    if (reason === 'expiring') return t('filterExpiring', 'Expiring soon');
    if (reason === 'quota') return t('filterQuota', 'Near quota');
    return t('filterDisabled', 'Disabled');
  }, [t]);

  const [userTab, setUserTab] = useState('online');
  const previewUsers = (users || [])
    .filter((u) => u?.name && Number(u.active_connections || 0) > 0)
    .sort((a, b) => Number(b.active_connections || 0) - Number(a.active_connections || 0))
    .slice(0, 8);

  const userColumns = useMemo(() => [
    {
      key: 'name', label: t('th_user', 'User'),
      render: (u) => (
        <span className="dt-cell-main">
          <span className="dt-avatar" aria-hidden="true">{String(u.name).slice(0, 1).toUpperCase()}</span>
          <span className="dt-cell-title">{u.name}</span>
        </span>
      ),
    },
    { key: 'plan', label: t('th_plan', 'Plan'), hideOnMobile: true,
      render: (u) => (u.max_logins === 0 ? t('unlimited', 'Unlimited') : t('devicesCount', 'Devices: {{count}}', { count: u.max_logins })) },
    { key: 'status', label: t('th_status', 'Status'),
      render: (u) => <StatusBadge status={userStatusOf(u)} label={statusLabelFor(u, t)} /> },
    { key: 'used', label: t('th_dataUsed', 'Data'), className: 'dt-num',
      render: (u) => formatBytes(u.used || 0) },
    { key: 'sessions', label: t('th_sessions', 'Sessions'), className: 'dt-num', hideOnMobile: true,
      render: (u) => `${Number(u.active_connections || 0)}/${u.max_logins === 0 ? '∞' : (u.max_logins ?? '—')}` },
    { key: 'actions', label: t('th_actions', 'Actions'),
      render: (u) => (
        <span className="dt-actions">
          <button type="button" className="dt-icon-btn"
            title={`${t('manage', 'Manage')} ${u.name}`}
            aria-label={`${t('manage', 'Manage')} ${u.name}`}
            onClick={() => navigate(`/users?user=${u.uuid}`)}>
            <FiArrowRight size={15} aria-hidden="true" />
          </button>
        </span>
      ),
    },
  ], [t, navigate]);

  const attentionColumns = useMemo(() => [
    { key: 'name', label: t('th_user', 'User'),
      render: ({ user: u }) => (
        <span className="dt-cell-main">
          <span className="dt-avatar" aria-hidden="true">{String(u.name).slice(0, 1).toUpperCase()}</span>
          <span className="dt-cell-title">{u.name}</span>
        </span>
      ),
    },
    { key: 'reason', label: t('th_reason', 'Needs'),
      render: ({ reasons }) => (
        <span className="ds-reasons">
          {reasons.map((r) => (
            <span key={r} className={`ds-reason${r === 'disabled' ? ' ds-reason--danger' : ''}`}>{attentionReasonLabel(r)}</span>
          ))}
        </span>
      ),
    },
    { key: 'actions', label: t('th_actions', 'Actions'),
      render: ({ user: u }) => (
        <span className="dt-actions">
          <button type="button" className="dt-icon-btn"
            title={`${t('manage', 'Manage')} ${u.name}`}
            aria-label={`${t('manage', 'Manage')} ${u.name}`}
            onClick={() => navigate(`/users?user=${u.uuid}`)}>
            <FiArrowRight size={15} aria-hidden="true" />
          </button>
        </span>
      ),
    },
  ], [t, navigate, attentionReasonLabel]);

  const userTabs = useMemo(() => [
    { id: 'online', label: t('filterOnline', 'Online'), count: onlineTotal },
    { id: 'attention', label: t('needsAttention', 'Needs attention'), count: attentionUsers.length },
  ], [t, onlineTotal, attentionUsers.length]);

  const allFailed = !loading
    && Boolean(errors.users && errors.activity)
    && (isOwner ? Boolean(errors.stats && errors.nodes && errors.metrics) : true);

  const heroLoading = loading && !users && (isOwner ? (!stats && !nodes) : true);

  return (
    <div className="ds-page">
      <PageHeader
        title={t('operationalOverview', 'Operations')}
        icon={<FiActivity />}
        meta={(
          <span className="ds-live">
            <span className="ds-live-dot" aria-hidden="true" />
            <span>{t('liveOperations', 'Live operations')}</span>
            {lastUpdated ? (
              <span className="ds-updated" aria-live="polite">
                · {t('updatedAt', 'Updated')} {fmtUpdated(lastUpdated)}
              </span>
            ) : null}
            {refreshStale && <span className="ds-updated-stale"> · {t('staleData', 'Stale — refresh failed')}</span>}
          </span>
        )}
        actions={(
          <>
            <Button variant="primary" size="sm" icon={<FiPlus size={12} aria-hidden="true" />} onClick={() => navigate('/users?add=1')}>
              {t('addUser', 'Add user')}
            </Button>
            {isOwner && (
              <Button variant="secondary" size="sm" icon={<FiPlus size={12} aria-hidden="true" />} onClick={() => navigate('/nodes?add=1')}>
                {t('addNode', 'Add node')}
              </Button>
            )}
          </>
        )}
      />

      {heroLoading ? (
        <div role="status" aria-live="polite" aria-label={t('loading', 'Loading…')}>
          {isOwner && <div className="ds-hero-skeleton" aria-hidden="true" />}
          <div className="ds-hero">
            {Array.from({ length: isOwner ? 4 : 4 }, (_, i) => (
              <div className="ds-kpi ds-kpi--loading" key={i} aria-hidden="true" />
            ))}
          </div>
        </div>
      ) : (
        <>
          {isOwner ? (
            <Card className="ds-hero-card">
              <div className="ds-hero-now">
                <span className="ds-hero-icon" aria-hidden="true"><FiActivity size={18} /></span>
                <div className="ds-hero-figure">
                  <span className="ds-hero-value" dir="ltr">
                    {probesPending ? '—' : activeConnections.toLocaleString()}
                  </span>
                  <span className="ds-hero-label">
                    {t('heroNowLabel', 'Live connections')}
                    <span className="ds-live">
                      <span className="ds-live-dot" aria-hidden="true" />
                      {lastUpdated ? fmtUpdated(lastUpdated) : null}
                      {refreshStale ? ` · ${t('staleData', 'Stale')}` : ''}
                    </span>
                  </span>
                </div>
              </div>
              <StreamChart />
            </Card>
          ) : null}
          <div className="ds-hero">
            <KpiCard
              icon={FiUsers}
              label={t('onlineUsers', 'Online Users')}
              value={String(onlineTotal)}
              animate={onlineTotal}
              tone={onlineTotal ? 'ok' : null}
              to="/users?view=online"
              sub={attentionUsers.length ? t('heroUsersWarn', '{{count}} need attention', { count: attentionUsers.length }) : t('heroUsersOk', 'Nobody waiting')}
            />
            <KpiCard
              icon={FiUsers}
              label={t('totalUsers', 'Total Users')}
              value={errors.users ? '—' : String(totalUsers)}
              animate={errors.users ? undefined : totalUsers}
              to="/users"
              sub={t('usersSummarySub', '{{active}} active · {{online}} online', { active: activeTotal, online: onlineTotal })}
            />
            <KpiCard
              icon={FiBarChart2}
              label={isOwner ? t('trafficToday', 'Traffic 24h') : t('totalTraffic', 'Total Traffic')}
              value={isOwner
                ? (trafficToday === null ? '—' : formatBytes(trafficToday))
                : (errors.users ? '—' : formatBytes(totalUsed))}
              animate={isOwner ? undefined : (errors.users ? undefined : totalUsed)}
              format={isOwner ? undefined : formatBytes}
              spark={trafficSeries.bytes}
              sub={isOwner ? t('trafficTodaySub', 'Growth in the last 24 hours') : t('heroTrafficSub', 'All users combined')}
            />
            {isOwner ? (
              <KpiCard
                icon={FiServer}
                label={t('onlineNodes', 'Nodes online')}
                value={probesPending ? '—' : `${onlineNodes}/${nodes?.length || 0}`}
                tone={offlineNodes ? 'warn' : 'ok'}
                to="/nodes"
                sub={offlineNodes ? t('heroNodesWarn', '{{count}} offline', { count: offlineNodes }) : t('heroNodesOk', 'All reachable')}
              />
            ) : (
              <KpiCard
                icon={FiActivity}
                label={t('activeConnections', 'Active Connections')}
                value={activeConnections.toLocaleString()}
                sub={t('heroConnsSub', '{{count}} sessions live', { count: activeConnections })}
              />
            )}
          </div>
        </>
      )}

      {!loading && <AlertStrip items={notifications} />}

      {allFailed ? (
        <div className="ds-empty-wrap">
          <ErrorState
            title={t('loadFailedTitle')}
            message={t('loadFailedMessage')}
            onRetry={() => loadData()}
            retryLabel={t('retry')}
          />
        </div>
      ) : (
        <>
          {isOwner && (
            <Card
              title={t('fleetHealthTitle', 'Fleet health')}
              icon={<FiServer aria-hidden="true" />}
            >
              <div className="ds-fleet">
                <ServerHealth
                  stats={stats}
                  traffic={trafficSeries}
                  error={errors.stats}
                  loading={loading}
                  onRetry={() => loadData()}
                  onlineNodes={onlineNodes}
                  totalNodes={nodes?.length || 0}
                  embedded
                />
                <div className="ds-fleet-nodes">
                  <div className="ds-node-summary">
                    <Badge tone="success" dot>{t('statusOnline', 'Online')}: {onlineNodes}</Badge>
                    <Badge tone={offlineNodes ? 'danger' : 'neutral'} dot>{t('statusDown', 'Down')}: {offlineNodes}</Badge>
                    <span className="ds-node-summary-total">
                      {t('nodesTotal', 'Total Nodes')}: {nodes?.length || 0}
                    </span>
                  </div>
                  {loading ? (
                    <SkeletonTable rows={4} cols={4} label={t('loading', 'Loading…')} />
                  ) : nodeHealthRows.length > 0 ? (
                    <ul className="ds-node-list">
                      {nodeHealthRows.slice(0, 6).map(({ node, status, live, latency, meta }) => (
                        <li key={node.id} className="ds-node-row">
                          <span className="ds-node-name">
                            {meta.flagCode && <FlagIcon code={meta.flagCode} />}
                            <span title={node.name}>{node.name}</span>
                          </span>
                          <StatusBadge
                            status={status === 'online' ? 'online' : 'offline'}
                            label={status === 'online' ? t('statusOnline', 'Online') : status === 'off' ? t('statusOff', 'Off') : t('statusDown', 'Down')}
                          />
                          <span className="ds-node-metric">{live} {t('th_sessions', 'Sessions')}</span>
                          <span className="ds-node-metric">{latency > 0 ? `${latency} ms` : '—'}</span>
                          <button
                            type="button"
                            className="ds-node-arrow"
                            aria-label={`${t('clickToManageNode', 'Click to manage node')} ${node.name}`}
                            onClick={() => navigate('/nodes')}
                          >
                            <FiArrowRight size={14} aria-hidden="true" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState
                      title={t('noNodes', 'No nodes')}
                      description={t('noNodesDesc', 'Add a node to see its live status on the map and table.')}
                      actionLabel={t('addNode', 'Add node')}
                      onAction={() => navigate('/nodes')}
                    />
                  )}
                </div>
              </div>
            </Card>
          )}

          <div className="ds-grid-2">
            <Card
              title={t('users', 'Users')}
              icon={<FiUsers aria-hidden="true" />}
              actions={(
                <Button variant="secondary" size="sm" onClick={() => navigate(userTab === 'attention' ? '/users' : '/users?view=online')}>
                  {t('viewAll', 'View all')}
                </Button>
              )}
            >
              <Tabs tabs={userTabs} value={userTab} onChange={setUserTab} ariaLabel={t('users', 'Users')} />
              <div className="ds-users-panel">
                {userTab === 'online' ? (
                  previewUsers.length > 0 ? (
                    <>
                      <DataTable
                        columns={userColumns}
                        rows={previewUsers}
                        rowKey={(r) => String(r.uuid || r.name)}
                        density="comfort"
                        caption={t('onlineUsers', 'Online users')}
                      />
                      <div className="ds-panel-foot">
                        <span>{t('showingPreview', 'Showing {{shown}} of {{total}} online', { shown: previewUsers.length, total: onlineTotal })}</span>
                      </div>
                    </>
                  ) : (
                    <EmptyState
                      title={t('noUsersOnline', 'No users online')}
                      description={t('noUsersOnlineDesc', 'Online users will appear here.')}
                      actionLabel={t('viewAll', 'View all')}
                      onAction={() => navigate('/users')}
                    />
                  )
                ) : (
                  attentionUsers.length > 0 ? (
                    <DataTable
                      columns={attentionColumns}
                      rows={attentionUsers.slice(0, 8)}
                      rowKey={(r) => String(r.user.uuid || r.user.name)}
                      density="comfort"
                      caption={t('needsAttention', 'Needs attention')}
                    />
                  ) : (
                    <EmptyState
                      title={t('allSystemsClear', 'All systems clear')}
                      description={t('noAttentionDesc', 'No expiring, over-quota or disabled users right now.')}
                    />
                  )
                )}
              </div>
            </Card>

            <ActivityFeed
              items={activity}
              error={errors.activity}
              loading={loading}
              onRetry={() => loadData()}
            />
          </div>

        </>
      )}
    </div>
  );
};

export default ServerStats;
