// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { FiActivity, FiServer, FiUsers, FiBarChart2, FiPlus, FiAlertTriangle, FiArrowRight } from 'react-icons/fi';
import { formatBytes } from '../utils/format';
import { daysUntil } from '../utils/time';
import { readPrefs, alertPrefKey } from '../utils/notifPrefs';
import { nodeMeta } from '../utils/geo.js';
import FlagIcon from '../utils/geo.jsx';
import { settle } from '../hooks/useAsyncData';
import { useLive } from '../context/LiveContext';
import { DataTable, StatusBadge, ErrorState, EmptyState, SkeletonTable } from '../components/ui';
import KpiCard from '../components/dashboard/KpiCard';
import AlertStrip from '../components/dashboard/AlertStrip';
import ServerHealth from '../components/dashboard/ServerHealth';
import SessionsBreakdown from '../components/dashboard/SessionsBreakdown';
import ActivityFeed from '../components/dashboard/ActivityFeed';
import StreamChart from '../components/dashboard/StreamChart';
import { Panel, PanelState } from '../components/dashboard/Panel';
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
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

const ServerStats = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();

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
      stats: apiClient.get('/server/info'),
      users: apiClient.get('/users/'),
      nodes: apiClient.get('/nodes/'),
      metrics: apiClient.get('/metrics/history?hours=24'),
      notifs: apiClient.get('/notifications/'),
      activity: apiClient.get('/activity/?limit=8'),
    });

    const nextErrors = {};

    if (res.stats.ok) setStats(res.stats.data.data?.data || res.stats.data.data || null);
    else nextErrors.stats = res.stats.error;

    if (res.users.ok) setUsers(asList(res.users.data, 'users'));
    else nextErrors.users = res.users.error;

    let nodesData = [];
    if (res.nodes.ok) {
      nodesData = asList(res.nodes.data, 'nodes');
      setNodes(nodesData);
    } else nextErrors.nodes = res.nodes.error;

    if (res.metrics.ok) {
      const series = res.metrics.data.data?.data?.traffic || res.metrics.data.data?.traffic || [];
      setTrafficSeries({
        conns: series.map((p) => Number(p.active_connections || 0)),
        bytes: series.map((p) => Number(p.total_used || 0)),
      });
    } else nextErrors.metrics = res.metrics.error;

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
  }, []);

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
  const activeConnections = Object.values(nodeStatus).reduce((sum, s) => sum + Number(s?.session_diagnostics?.live_count || 0), 0);
  const totalUsed = (users || []).reduce((sum, u) => sum + Number(u.used || 0), 0);
  const activeNodeCount = (nodes || []).filter((n) => n.status).length;
  const offlineNodes = probesDone ? Math.max(0, activeNodeCount - onlineNodes) : 0;
  const onlineTotal = (users || []).filter((u) => Number(u.active_connections || 0) > 0).length;
  const probesReady = probesDone || (nodes?.length || 0) === 0;
  const probesPending = !probesReady;
  const notifications = deriveNotifications({ users, nodes, nodeStatus, serverNotifs, probesReady, t });

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

  const nodeColumns = useMemo(() => [
    { key: 'name', label: t('th_id', 'Node'),
      render: (node) => {
        const meta = nodeMeta(node);
        return (
          <span className="dt-cell-main">
            {meta.flagCode && <FlagIcon code={meta.flagCode} />}
            <span style={{ minWidth: 0 }}>
              <span className="dt-cell-title">{node.name}</span>
              <br />
              <span className="dt-cell-sub">{meta.name}{meta.approximate ? ` (${t('approximate', 'approx.')})` : ''}</span>
            </span>
          </span>
        );
      },
    },
    { key: 'status', label: t('th_status', 'Status'),
      render: (node) => {
        const st = nodeStatus[node.id] || {};
        const reachable = node.status && (st.reachable === true || (st.reachable === undefined && st.node_info !== undefined));
        return <StatusBadge status={reachable ? 'online' : 'offline'} label={reachable ? t('statusOnline', 'Online') : (node.status ? t('statusDown', 'Down') : t('statusOff', 'Off'))} />;
      },
    },
    { key: 'cpu', label: t('th_cpu', 'CPU'), className: 'dt-num', hideOnMobile: true,
      render: (node) => {
        const cpu = nodeStatus[node.id]?.node_info?.cpu_usage;
        return Number.isFinite(Number(cpu)) ? `${Number(cpu).toFixed(0)}%` : '—';
      },
    },
    { key: 'mem', label: t('kv_memory', 'Memory'), className: 'dt-num', hideOnMobile: true,
      render: (node) => {
        const mem = nodeStatus[node.id]?.node_info?.memory_usage;
        return Number.isFinite(Number(mem)) ? `${Number(mem).toFixed(0)}%` : '—';
      },
    },
    { key: 'conns', label: t('th_conns', 'Conns'), className: 'dt-num',
      render: (node) => {
        const st = nodeStatus[node.id] || {};
        const conns = Number(st.session_diagnostics?.live_count || 0);
        return st.latency_ms ? `${conns} · ${st.latency_ms}ms` : `${conns}`;
      },
    },
  ], [t, nodeStatus]);

  const allFailed = !loading
    && Boolean(errors.stats && errors.users && errors.nodes && errors.activity && errors.metrics);

  const heroLoading = loading && !stats && !users && !nodes;

  return (
    <div className="ds-page">
      <div className="ds-header">
        <div className="ds-header-copy">
          <h1>{t('operationalOverview', 'Operations')}</h1>
          <p className="ds-live">
            <span className="ds-live-dot" aria-hidden="true" />
            <span>{t('liveOperations', 'Live operations')}</span>
            <span className="ds-updated" aria-live="polite">
              · {t('updatedAt', 'Updated')} {fmtUpdated(lastUpdated)}
              {refreshStale && <span className="ds-updated-stale"> · {t('staleData', 'Stale — refresh failed')}</span>}
            </span>
          </p>
        </div>
        <div className="ds-header-actions">
          <button type="button" className="btn btn-sm" onClick={() => navigate('/users?add=1')}>
            <FiPlus size={12} aria-hidden="true" /> {t('addUser', 'Add user')}
          </button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate('/nodes?add=1')}>
            <FiPlus size={12} aria-hidden="true" /> {t('addNode', 'Add node')}
          </button>
        </div>
      </div>

      {heroLoading ? (
        <div className="ds-hero" role="status" aria-live="polite" aria-label={t('loading', 'Loading…')}>
          {[0, 1, 2, 3].map((i) => (
            <div className="ds-kpi ds-kpi--loading" key={i} aria-hidden="true" />
          ))}
        </div>
      ) : (
        <div className="ds-hero">
          <KpiCard
            icon={FiActivity}
            label={t('activeConnections', 'Active sessions')}
            value={probesPending ? '—' : activeConnections.toLocaleString()}
            animate={probesPending ? undefined : activeConnections}
            spark={trafficSeries.conns}
            to="/users?view=online"
            sub={t('heroConnsSub', '{{count}} sessions live', { count: probesPending ? 0 : activeConnections })}
          />
          <KpiCard
            icon={FiBarChart2}
            label={t('totalTraffic', 'Total bandwidth')}
            value={errors.users ? '—' : formatBytes(totalUsed)}
            animate={errors.users ? undefined : totalUsed}
            format={formatBytes}
            spark={trafficSeries.bytes}
            sub={t('heroTrafficSub', 'All users combined')}
          />
          <KpiCard
            icon={FiServer}
            label={t('onlineNodes', 'Nodes online')}
            value={probesPending ? '—' : `${onlineNodes}/${nodes?.length || 0}`}
            tone={offlineNodes ? 'warn' : 'ok'}
            to="/nodes"
            sub={offlineNodes ? t('heroNodesWarn', '{{count}} offline', { count: offlineNodes }) : t('heroNodesOk', 'All reachable')}
          />
          <KpiCard
            icon={FiUsers}
            label={t('onlineUsers', 'Users online')}
            value={String(onlineTotal)}
            tone={onlineTotal ? 'ok' : null}
            to={attentionUsers.length ? '/users' : '/users?view=online'}
            sub={attentionUsers.length ? t('heroUsersWarn', '{{count}} need attention', { count: attentionUsers.length }) : t('heroUsersOk', 'Nobody waiting')}
          />
        </div>
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
          <StreamChart period="24h" hours={24} />

          <div className="ds-grid-1-2">
            <ServerHealth
              stats={stats}
              traffic={trafficSeries}
              error={errors.stats}
              loading={loading}
              onRetry={() => loadData()}
              onlineNodes={onlineNodes}
              totalNodes={nodes?.length || 0}
            />
            <SessionsBreakdown
              nodes={nodes}
              nodeStatus={nodeStatus}
              error={errors.nodes}
              loading={loading}
              onRetry={() => loadData()}
            />
          </div>

          <div className="ds-grid-2">
            <section className="ds-card">
              <div className="ds-card-head">
                <h3 className="ds-card-title">
                  {t('users', 'Users')}
                </h3>
                <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate(userTab === 'attention' ? '/users' : '/users?view=online')}>
                  {t('viewAll', 'View all')}
                </button>
              </div>
              <div className="ds-card-body">
                <div className="ds-tabs" role="tablist" aria-label={t('users', 'Users')}>
                  <button type="button" role="tab" aria-selected={userTab === 'online'}
                    className={`ds-tab${userTab === 'online' ? ' active' : ''}`}
                    onClick={() => setUserTab('online')}>
                    {t('filterOnline', 'Online')} <span className="ds-tab-count">{onlineTotal}</span>
                  </button>
                  <button type="button" role="tab" aria-selected={userTab === 'attention'}
                    className={`ds-tab${userTab === 'attention' ? ' active' : ''}`}
                    onClick={() => setUserTab('attention')}>
                    {t('needsAttention', 'Needs attention')} <span className="ds-tab-count">{attentionUsers.length}</span>
                  </button>
                </div>
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
            </section>

            <ActivityFeed
              items={activity}
              error={errors.activity}
              loading={loading}
              onRetry={() => loadData()}
            />
          </div>

          <section className="ds-card">
            <div className="ds-card-head">
                <h3 className="ds-card-title">
                  {t('nodeMap', 'Nodes')}
                </h3>
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => navigate('/nodes')}>
                {t('viewAll', 'View all')}
              </button>
            </div>
            <div className="ds-card-body">
              {loading ? (
                <SkeletonTable rows={6} cols={5} label={t('loading', 'Loading…')} />
              ) : errors.nodes ? (
                <div className="ds-inline-error" role="alert">
                  <FiAlertTriangle aria-hidden="true" />
                  <div>
                    <strong>{t('panelLoadFailed', 'Could not load this panel')}</strong>
                    <span>{t('panelLoadFailedHint', 'Other sections are unaffected.')}</span>
                  </div>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => loadData()}>
                    {t('retry', 'Retry')}
                  </button>
                </div>
              ) : (nodes || []).length > 0 ? (
                <>
                  <DataTable
                    columns={nodeColumns}
                    rows={(nodes || []).slice(0, 8)}
                    rowKey={(r) => String(r.id)}
                    density="comfort"
                    caption={t('nodeMap', 'Nodes')}
                  />
                  {(nodes || []).length > 8 && (
                    <div className="ds-panel-foot">
                      <span>{t('showingPreviewNodes', 'Showing 8 of {{total}} nodes', { total: (nodes || []).length })}</span>
                    </div>
                  )}
                </>
              ) : (
                <EmptyState
                  title={t('noNodes', 'No nodes')}
                  description={t('noNodesDesc', 'Add your first node to get started.')}
                  actionLabel={t('addNode', 'Add node')}
                  onAction={() => navigate('/nodes')}
                />
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
};

export default ServerStats;
