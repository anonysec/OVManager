import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  FiDownload, FiSearch, FiPlus, FiCheck, FiWifi, FiX,
  FiEdit2, FiActivity, FiTrash2, FiCopy, FiClock, FiUserCheck, FiUserX, FiRefreshCw,
} from 'react-icons/fi';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { buildSubscriptionLink } from '../utils/subscription';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import { useTranslation } from 'react-i18next';
import { daysUntil, fmtRelative, fmtDate } from '../utils/time';
import { formatBytes } from '../utils/format';
import { copyText } from '../utils/clipboard';
import UserFormModal from '../components/UserFormModal';
import ExtendUserModal from '../components/ExtendUserModal';
import SelectNodeForDownloadModal from '../components/SelectNodeForDownloadModal';
import UserSessionsModal from '../components/UserSessionsModal';
import UserDetailModal from '../components/UserDetailModal';
import ConfirmModal from '../components/ConfirmModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import DataTable from '../components/ui/DataTable';
import StatusBadge from '../components/ui/StatusBadge';

const PAGE_SIZE_KEY = 'ovmanager-ui-users-pagesize';
const SORT_KEY = 'ovmanager-ui-users-sort';

const statusOf = (u) => {
  const online = u.online || Number(u.active_connections || 0) > 0;
  if (online) return 'online';
  const d = daysUntil(u.expiry_date);
  if (d < 0 || d === -Infinity) return u.is_active === false ? 'offline' : 'danger';
  if (u.is_active === false) return 'offline';
  if (d <= 7) return 'warning';
  return 'idle';
};

const statusLabel = (u, t) => {
  const online = u.online || Number(u.active_connections || 0) > 0;
  if (online) return t('statusOnline');
  const d = daysUntil(u.expiry_date);
  if (d < 0) return t('expired');
  if (u.is_active === false) return t('disabled');
  return t('statusOffline');
};

const UserManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [users, setUsers] = useState([]);
  const [subSettings, setSubSettings] = useState(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isExtendModalOpen, setIsExtendModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [isSessionsModalOpen, setIsSessionsModalOpen] = useState(false);
  const [sessionDiagnostics, setSessionDiagnostics] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState('');
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [lastDeleted, setLastDeleted] = useState(null);
  const [density, setDensity] = useState(() => localStorage.getItem('ovmanager-ui-density') || 'comfort');

  const [sort, setSort] = useState(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(SORT_KEY) || 'null');
      if (raw?.key) return raw;
    } catch { /* ignore */ }
    return { key: 'name', dir: 'asc' };
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25);

  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null, danger: true, confirmLabel: null });
  const openConfirm = (title, message, onConfirm, danger = true, confirmLabel = null) =>
    setConfirm({ open: true, title, message, onConfirm, danger, confirmLabel });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  const fetchUsers = useCallback(async ({ background = false } = {}) => {
    setLoadError(false);
    if (!background) setIsLoading((prev) => (users.length === 0 ? true : prev));
    try {
      const response = await apiClient.get('/users/');
      const list = asList(response.data, 'users');
      setUsers(list);
      setLoadError(false);
    } catch {
      setLoadError(true);
      if (!background) addToast(t('loadError', 'Failed to load users'), 'error');
    } finally {
      setIsLoading(false);
    }
  }, [addToast, users.length, t]);

  const fetchSubSettings = useCallback(async () => {
    try {
      const res = await apiClient.get('/server/settings');
      const data = res.data?.data || res.data;
      if (data?.subscription_url_prefix) setSubSettings(data);
    } catch { /* subscription links degrade to hidden, table still works */ }
  }, []);

  const { subscribe } = useLive();
  useEffect(() => {
    const u1 = subscribe('users.changed', () => fetchUsers({ background: true }));
    const u2 = subscribe('users.created', () => fetchUsers({ background: true }));
    const u3 = subscribe('users.deleted', () => fetchUsers({ background: true }));
    const u4 = subscribe('tick', () => {});
    return () => { u1(); u2(); u3(); u4(); };
  }, [subscribe, fetchUsers]);

  useEffect(() => { fetchUsers(); fetchSubSettings(); }, [fetchUsers, fetchSubSettings]);

  useEffect(() => {
    if (!lastDeleted) return undefined;
    const id = setTimeout(() => setLastDeleted(null), 120000);
    return () => clearTimeout(id);
  }, [lastDeleted]);

  const userStats = useMemo(() => ({
    total: users.length,
    active: users.filter(u => u.is_active).length,
    online: users.filter(u => u.online || Number(u.active_connections || 0) > 0).length,
    inactive: users.filter(u => !u.is_active).length,
  }), [users]);

  const filterCounts = useMemo(() => {
    const c = (fn) => users.filter(fn).length;
    return {
      all: users.length,
      online: c(u => u.online || Number(u.active_connections || 0) > 0),
      expiring: c(u => { const d = daysUntil(u.expiry_date); return d >= 0 && d <= 7; }),
      quota: c(u => Number(u.total) > 0 && (Number(u.used || 0) / Number(u.total)) >= 0.85),
      disabled: c(u => !u.is_active),
      unlimited: c(u => u.total === null || u.total === 0),
    };
  }, [users]);

  const searchTerm = searchParams.get('q') || '';
  const view = searchParams.get('view') || 'all';
  const patchParams = useCallback((mutate) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  const setSearchTerm = (value) => { setPage(1); patchParams((p) => { if (value) p.set('q', value); else p.delete('q'); }); };
  const setView = (value) => { setPage(1); patchParams((p) => { if (value && value !== 'all') p.set('view', value); else p.delete('view'); }); };

  const filteredUsers = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return users.filter((user) => {
      if (term) {
        const hay = `${user.name || ''} ${user.uuid || ''} ${user.owner || ''}`.toLowerCase();
        if (!hay.includes(term)) return false;
      }
      if (view === 'online' && !(user.online || Number(user.active_connections || 0) > 0)) return false;
      if (view === 'expiring') { const d = daysUntil(user.expiry_date); if (!(d >= 0 && d <= 7)) return false; }
      if (view === 'quota') { if (!(Number(user.total) > 0 && (Number(user.used || 0) / Number(user.total)) >= 0.85)) return false; }
      if (view === 'disabled' && user.is_active) return false;
      if (view === 'unlimited' && (user.total !== null && user.total !== 0)) return false;
      return true;
    });
  }, [users, searchTerm, view]);

  const sortedUsers = useMemo(() => {
    const arr = [...filteredUsers];
    const { key, dir } = sort;
    const mul = dir === 'desc' ? -1 : 1;
    const val = (u) => {
      switch (key) {
        case 'name': return (u.name || '').toLowerCase();
        case 'expiry_date': return u.expiry_date || '9999';
        case 'used': return Number(u.used || 0);
        case 'total': return u.total == null ? Infinity : Number(u.total);
        case 'active_connections': return Number(u.active_connections || 0);
        case 'last_online': return u.last_online || '';
        case 'owner': return (u.owner || '').toLowerCase();
        case 'status': return statusOf(u);
        default: return u[key];
      }
    };
    arr.sort((a, b) => {
      const va = val(a); const vb = val(b);
      if (va < vb) return -1 * mul;
      if (va > vb) return 1 * mul;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
    return arr;
  }, [filteredUsers, sort]);

  const pagedUsers = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sortedUsers.slice(start, start + pageSize);
  }, [sortedUsers, page, pageSize]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(sortedUsers.length / pageSize));
    if (page > totalPages) setPage(totalPages);
  }, [sortedUsers.length, pageSize, page]);

  useEffect(() => {
    setSelected((prev) => {
      const ids = new Set(sortedUsers.map((u) => String(u.uuid)));
      const next = new Set([...prev].filter((k) => ids.has(k)));
      return next.size === prev.size ? prev : next;
    });
  }, [sortedUsers]);

  const onSort = useCallback((key) => {
    setSort((prev) => {
      const next = prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' };
      localStorage.setItem(SORT_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  // Deep-link ?user=<uuid> opens the detail modal (used by dashboard previews).
  useEffect(() => {
    const uuid = searchParams.get('user');
    if (!uuid || users.length === 0) return;
    const found = users.find((u) => String(u.uuid) === String(uuid));
    if (found) {
      setSelectedUser(found);
      setIsDetailModalOpen(true);
      patchParams((p) => p.delete('user'));
    }
  }, [searchParams, users, patchParams]);

  const getSubscriptionLink = useCallback((user) => {
    if (!user?.uuid) return '';
    return buildSubscriptionLink(subSettings, user.uuid);
  }, [subSettings]);

  const handleToggleStatus = useCallback(async (user) => {
    const next = !user.is_active;
    try {
      const res = await apiClient.put(`/users/${user.uuid}/status`, { name: user.name, status: next });
      if (res.data?.success) {
        addToast(t(next ? 'userEnabled' : 'userDisabled', next ? 'User {{name}} enabled.' : 'User {{name}} disabled.', { name: user.name }), 'success');
      } else {
        addToast(res.data?.msg || t('error'), 'error');
      }
      fetchUsers({ background: true });
    } catch (e) {
      addToast(e.response?.data?.detail || t('error'), 'error');
    }
  }, [addToast, fetchUsers, t]);

  const handleDelete = useCallback((user) => {
    openConfirm(
      t('deleteUser', 'Delete user'),
      t('confirmDelete', 'Delete {{name}} and all their data?', { name: user.name }),
      async () => {
        try {
          const res = await apiClient.delete(`/users/${user.uuid}`);
          if (res.data?.success) {
            setLastDeleted({ uuid: user.uuid, name: user.name });
            setSelected((prev) => { const n = new Set(prev); n.delete(String(user.uuid)); return n; });
            addToast(t('userDeletedUndo', 'User {{name}} deleted', { name: user.name }), 'success');
          } else {
            addToast(res.data?.msg || t('error'), 'error');
          }
          fetchUsers({ background: true });
        } catch { addToast(t('error'), 'error'); }
      },
      true,
      t('deleteUser')
    );
  }, [addToast, fetchUsers, t]);

  const handleUndoDelete = useCallback(async () => {
    if (!lastDeleted) return;
    try {
      const res = await apiClient.post(`/users/${lastDeleted.uuid}/restore`);
      if (res.data?.success) {
        addToast(t('userRestored', 'User {{name}} restored.', { name: lastDeleted.name }), 'success');
        setLastDeleted(null);
        fetchUsers({ background: true });
      } else {
        addToast(res.data?.msg || t('undoFailed', 'Undo failed — user could not be restored.'), 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || t('undoFailed', 'Undo failed — user could not be restored.'), 'error');
    }
  }, [lastDeleted, addToast, fetchUsers, t]);

  const handleExtend = useCallback(async (user, { days, bytes }) => {
    const res = await apiClient.post(`/users/${user.uuid}/extend`, { days, bytes });
    if (res.data?.success) {
      addToast(t('extended', 'User {{name}} extended.', { name: user.name }), 'success');
      fetchUsers({ background: true });
    } else {
      throw new Error(res.data?.msg || t('error'));
    }
  }, [addToast, fetchUsers, t]);

  const handleShowSessions = useCallback(async (user) => {
    setSelectedUser(user);
    setSessionLoading(true);
    setSessionError('');
    setSessionDiagnostics(null);
    setIsSessionsModalOpen(true);
    try {
      const res = await apiClient.get(`/users/${user.uuid}/sessions`);
      setSessionDiagnostics(res.data?.data || res.data);
    } catch (e) {
      setSessionError(e.response?.data?.detail || e.message || t('error'));
    } finally {
      setSessionLoading(false);
    }
  }, [t]);

  const handleDisconnect = useCallback(async () => {
    if (!selectedUser) return;
    try {
      const res = await apiClient.post(`/users/${selectedUser.uuid}/disconnect`);
      addToast(res.data?.msg || t('disconnected', 'Disconnect requested'), 'success');
      const refreshed = await apiClient.get(`/users/${selectedUser.uuid}/sessions`).catch(() => null);
      if (refreshed) setSessionDiagnostics(refreshed.data?.data || refreshed.data);
    } catch (e) {
      addToast(e.response?.data?.detail || t('error'), 'error');
    }
  }, [selectedUser, addToast, t]);

  const handleEdit = useCallback((user) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  }, []);

  const handleOpenDownloadModal = useCallback((user) => {
    setSelectedUser(user);
    setIsDownloadModalOpen(true);
  }, []);

  const handleUserClick = useCallback((user) => {
    setSelectedUser(user);
    setIsDetailModalOpen(true);
  }, []);

  const handleResetUsage = useCallback(async (user) => {
    openConfirm(
      t('resetUsage'),
      t('confirmResetUsage', 'Reset all usage data for "{{name}}"? This cannot be undone.', { name: user.name }),
      async () => {
        try {
          const res = await apiClient.post(`/users/${user.uuid}/reset-usage`);
          addToast(res.data?.success ? t('usageResetSuccess', 'Usage for {{name}} has been reset.', { name: user.name }) : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          fetchUsers({ background: true });
        } catch { addToast(t('error'), 'error'); }
      },
      false,
      t('resetUsage')
    );
  }, [addToast, fetchUsers, t]);

  const handleExportCsv = useCallback(() => {
    const esc = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const head = ['name', 'uuid', 'status', 'used_bytes', 'total_bytes', 'max_logins', 'expiry_date', 'last_online', 'owner'];
    const rows = filteredUsers.map((u) => [
      u.name, u.uuid, u.is_active ? 'active' : 'inactive', u.used || 0, u.total ?? '', u.max_logins ?? '', u.expiry_date || '', u.last_online || '', u.owner || '',
    ]);
    const csv = [head, ...rows].map((r) => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `ovmanager-users-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    addToast(t('exported', 'CSV exported'), 'success');
  }, [filteredUsers, addToast, t]);

  const runBulk = useCallback(async (op, label) => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    const ids = [...selected];
    let ok = 0; let fail = 0;
    const byUuid = new Map(users.map((u) => [String(u.uuid), u]));
    for (const uuid of ids) {
      const u = byUuid.get(String(uuid));
      if (!u) { fail += 1; continue; }
      try {
        if (op === 'delete') await apiClient.delete(`/users/${uuid}`);
        else if (op === 'enable') await apiClient.put(`/users/${uuid}/status`, { name: u.name, status: true });
        else if (op === 'disable') await apiClient.put(`/users/${uuid}/status`, { name: u.name, status: false });
        else if (op === 'reset') await apiClient.post(`/users/${uuid}/reset-usage`);
        else if (op === 'extend30') await apiClient.post(`/users/${uuid}/extend`, { days: 30, bytes: 0 });
        ok += 1;
      } catch { fail += 1; }
    }
    setBulkBusy(false);
    if (op === 'delete') setSelected(new Set());
    fetchUsers({ background: true });
    addToast(
      fail === 0
        ? t('bulkDone', '{{label}}: {{ok}} done.', { label, ok })
        : t('bulkPartial', '{{label}}: {{ok}} done, {{fail}} failed.', { label, ok, fail }),
      fail === 0 ? 'success' : 'warning'
    );
  }, [selected, users, fetchUsers, addToast, t]);

  const confirmBulk = (op, titleKey, msgKey, label) => {
    openConfirm(
      t(titleKey, label),
      t(msgKey, `${label} {{count}} selected users?`, { count: selected.size }),
      () => runBulk(op, label),
      op === 'delete',
      label
    );
  };

  const columns = useMemo(() => [
    {
      key: 'name', label: t('th_username', 'Username'), sortable: true,
      render: (u) => (
        <button type="button" className="dt-rowlink" onClick={() => handleUserClick(u)} title={u.uuid}>
          <span className="dt-cell-main">
            <span className="dt-avatar" aria-hidden="true">{String(u.name || '?').slice(0, 1).toUpperCase()}</span>
            <span style={{ minWidth: 0 }}>
              <span className="dt-cell-title">{u.name}</span>
              <br />
              <span className="dt-cell-sub">{String(u.uuid || '').slice(0, 8)}… · {u.owner || '—'}</span>
            </span>
          </span>
        </button>
      ),
    },
    {
      key: 'status', label: t('th_status', 'Status'), sortable: true,
      render: (u) => <StatusBadge status={statusOf(u)} label={statusLabel(u, t)} />,
    },
    {
      key: 'used', label: t('th_dataUsed', 'Data used'), sortable: true,
      render: (u) => {
        const used = Number(u.used || 0);
        const total = u.total == null || Number(u.total) === 0 ? null : Number(u.total);
        const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
        return (
          <span className="dt-usage">
            <span className="dt-usage-bar" aria-hidden="true">
              <span className={`dt-usage-fill${pct >= 95 ? ' is-danger' : pct >= 85 ? ' is-warn' : ''}`} style={{ width: `${total ? pct : 0}%` }} />
            </span>
            <span className="dt-num">{formatBytes(used)} / {total ? formatBytes(total) : '∞'}</span>
          </span>
        );
      },
    },
    {
      key: 'active_connections', label: t('th_sessions', 'Sessions'), sortable: true, className: 'dt-num', hideOnMobile: true,
      render: (u) => `${Number(u.active_connections || 0)}/${u.max_logins === 0 ? '∞' : (u.max_logins ?? '—')}`,
    },
    {
      key: 'expiry_date', label: t('th_expiryDate', 'Expiry'), sortable: true,
      render: (u) => {
        const d = daysUntil(u.expiry_date);
        return (
          <span className={d >= 0 && d <= 7 ? 'expiry-soon' : ''} title={fmtDate(u.expiry_date)}>
            {fmtDate(u.expiry_date)}
            {d !== Infinity && (
              <span className="dt-cell-sub" style={{ display: 'block' }}>
                {d < 0 ? t('expiredAgo', 'Expired {{days}} days ago', { days: Math.abs(d) }) : t('expiresIn', 'Expires in {{days}} days', { days: d })}
              </span>
            )}
          </span>
        );
      },
    },
    {
      key: 'last_online', label: t('th_lastOnline', 'Last online'), sortable: true, hideOnMobile: true,
      render: (u) => <span className="dt-num">{u.last_online ? fmtRelative(u.last_online) : t('never', 'Never')}</span>,
    },
    {
      key: 'actions', label: t('th_actions', 'Actions'),
      render: (u) => (
        <span className="dt-actions" role="group" aria-label={`${u.name} ${t('actions', 'Actions')}`}>
          <button type="button" className="dt-icon-btn" title={t('rowEdit', 'Edit')} aria-label={`${t('rowEdit', 'Edit')} ${u.name}`} onClick={() => handleEdit(u)}><FiEdit2 size={15} /></button>
          <button type="button" className="dt-icon-btn" title={t('rowSessions', 'Sessions')} aria-label={`${t('rowSessions', 'Sessions')} ${u.name}`} onClick={() => handleShowSessions(u)}><FiActivity size={15} /></button>
          <button type="button" className="dt-icon-btn" title={t('downloadConfig', 'Get Config')} aria-label={`${t('downloadConfig', 'Get Config')} ${u.name}`} onClick={() => handleOpenDownloadModal(u)}><FiDownload size={15} /></button>
          <button type="button" className="dt-icon-btn" title={t('extend', 'Extend')} aria-label={`${t('extend', 'Extend')} ${u.name}`} onClick={() => { setSelectedUser(u); setIsExtendModalOpen(true); }}><FiClock size={15} /></button>
          <button
            type="button" className="dt-icon-btn" title={u.is_active ? t('disableUser', 'Disable') : t('enableUser', 'Enable')}
            aria-label={`${u.is_active ? t('disableUser', 'Disable') : t('enableUser', 'Enable')} ${u.name}`}
            onClick={() => handleToggleStatus(u)}
          >
            {u.is_active ? <FiUserX size={15} /> : <FiUserCheck size={15} />}
          </button>
          <button type="button" className="dt-icon-btn" title={t('resetUsageButton', 'Reset usage')} aria-label={`${t('resetUsageButton', 'Reset usage')} ${u.name}`} onClick={() => handleResetUsage(u)}><FiRefreshCw size={15} /></button>
          <button type="button" className="dt-icon-btn is-danger" title={t('rowDelete', 'Delete')} aria-label={`${t('rowDelete', 'Delete')} ${u.name}`} onClick={() => handleDelete(u)}><FiTrash2 size={15} /></button>
        </span>
      ),
    },
  ], [t, handleUserClick, handleEdit, handleShowSessions, handleOpenDownloadModal, handleToggleStatus, handleResetUsage, handleDelete]);

  const allPageKeys = pagedUsers.map((u) => String(u.uuid));
  const allSelected = allPageKeys.length > 0 && allPageKeys.every((k) => selected.has(k));
  const someSelected = allPageKeys.some((k) => selected.has(k));

  return (
    <div id="users-view" className="view">
      <div className="view-header">
        <h2>{t('users')}</h2>
        <div className="view-header-actions">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => { const next = density === 'comfort' ? 'compact' : 'comfort'; setDensity(next); localStorage.setItem('ovmanager-ui-density', next); }} aria-pressed={density === 'compact'}>
            {t('density', 'Density')}: {t(density === 'compact' ? 'densityCompact' : 'densityComfort', density === 'compact' ? 'Compact' : 'Comfort')}
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleExportCsv}>
            <FiDownload size={14} aria-hidden="true" /> {t('exportCsv')}
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setIsAddModalOpen(true)}>
            <FiPlus size={14} aria-hidden="true" /> {t('addUser')}
          </button>
        </div>
      </div>

      <div className="user-stats-row" role="region" aria-label={t('userStats', 'User statistics')}>
        <div className="user-stat" style={{ '--us-accent': '#ff7a1e' }}>
          <span className="us-ico"><FiPlus aria-hidden="true" /></span>
          <span className="us-body"><span className="us-label">{t('totalUsers')}</span><span className="us-value">{userStats.total}</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#43a047' }}>
          <span className="us-ico"><FiCheck aria-hidden="true" /></span>
          <span className="us-body"><span className="us-label">{t('activeUsers')}</span><span className="us-value">{userStats.active}</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#66bb6a' }}>
          <span className="us-ico"><FiWifi aria-hidden="true" /></span>
          <span className="us-body"><span className="us-label">{t('onlineUsers')}</span><span className="us-value">{userStats.online}</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#e53935' }}>
          <span className="us-ico"><FiX aria-hidden="true" /></span>
          <span className="us-body"><span className="us-label">{t('inactiveUsers')}</span><span className="us-value">{userStats.inactive}</span></span>
        </div>
      </div>

      <div className="search-with-filters">
        <label className="search-field" style={{ flex: 1, maxWidth: 320 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input type="search" placeholder={t('searchByUsername')} value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="search-input" aria-label={t('searchByUsername')} />
        </label>
        <div className="results-meta" aria-live="polite">
          <strong>{filteredUsers.length}</strong> {t('results', 'results')}
          {(searchTerm || view !== 'all') && (
            <button type="button" className="toolbar-clear" onClick={() => { setSearchTerm(''); setView('all'); }}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

      <div className="user-filter-chips" role="group" aria-label={t('userFilters', 'User filters')}>
        {[
          { id: 'all', label: t('filterAll', 'All') },
          { id: 'online', label: t('filterOnline', 'Online') },
          { id: 'expiring', label: t('filterExpiring', 'Expiring soon') },
          { id: 'quota', label: t('filterQuota', 'Near quota') },
          { id: 'disabled', label: t('filterDisabled', 'Disabled') },
          { id: 'unlimited', label: t('filterUnlimited', 'Unlimited') },
        ].map((f) => (
          <button key={f.id} type="button" className={`filter-chip${view === f.id ? ' active' : ''}`} aria-pressed={view === f.id} onClick={() => setView(f.id)}>
            {f.label} <span className="count">{filterCounts[f.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {lastDeleted && (
        <div className="dt-bulkbar" role="status" aria-live="polite">
          <span>{t('userDeletedUndo', 'User {{name}} deleted', { name: lastDeleted.name })}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleUndoDelete}>{t('undo', 'Undo')}</button>
          <button type="button" className="toolbar-clear" onClick={() => setLastDeleted(null)} aria-label={t('dismiss', 'Dismiss')}>✕</button>
        </div>
      )}

      {selected.size > 0 && (
        <div className="dt-bulkbar" role="toolbar" aria-label={t('bulkActions', 'Bulk actions')}>
          <strong>{t('selectedCount', '{{count}} selected', { count: selected.size })}</strong>
          <button type="button" className="btn btn-secondary btn-sm" disabled={bulkBusy} onClick={() => confirmBulk('extend30', 'extend', 'confirmBulkExtend', t('extend30d', 'Extend +30 days'))}><FiClock size={13} /> {t('extend30d', 'Extend +30 days')}</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={bulkBusy} onClick={() => confirmBulk('enable', 'enableUsers', 'confirmBulkEnable', t('enable', 'Enable'))}><FiUserCheck size={13} /> {t('enable', 'Enable')}</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={bulkBusy} onClick={() => confirmBulk('disable', 'disableUsers', 'confirmBulkDisable', t('disable', 'Disable'))}><FiUserX size={13} /> {t('disable', 'Disable')}</button>
          <button type="button" className="btn btn-secondary btn-sm" disabled={bulkBusy} onClick={() => confirmBulk('reset', 'resetUsage', 'confirmBulkReset', t('resetUsageButton', 'Reset usage'))}><FiRefreshCw size={13} /> {t('resetUsageButton', 'Reset usage')}</button>
          <button type="button" className="btn btn-danger btn-sm" disabled={bulkBusy} onClick={() => confirmBulk('delete', 'deleteUsers', 'confirmBulkDelete', t('delete', 'Delete'))}><FiTrash2 size={13} /> {t('delete', 'Delete')}</button>
          <button type="button" className="toolbar-clear" onClick={() => setSelected(new Set())}>{t('clear', 'Clear')}</button>
        </div>
      )}

      {isLoading && users.length === 0 ? (
        <DataTable columns={columns} rows={[]} loading density={density} />
      ) : loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchUsers()} retryLabel={t('retry')} />
      ) : users.length === 0 ? (
        <EmptyState title={t('noUsersTitle')} description={t('noUsersBody')} actionLabel={t('addNewUser')} onAction={() => setIsAddModalOpen(true)} />
      ) : filteredUsers.length === 0 ? (
        <EmptyState
          title={t('noMatchesTitle', 'No matching users')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={() => { setSearchTerm(''); setView('all'); }}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={pagedUsers}
          rowKey={(r) => String(r.uuid)}
          sortKey={sort.key}
          sortDir={sort.dir}
          onSort={onSort}
          selectable
          selectedKeys={selected}
          allSelected={allSelected}
          someSelected={someSelected && !allSelected}
          onSelectAll={(checked) => {
            setSelected((prev) => {
              const next = new Set(prev);
              if (checked) allPageKeys.forEach((k) => next.add(k));
              else allPageKeys.forEach((k) => next.delete(k));
              return next;
            });
          }}
          onSelectRow={(k, checked) => {
            setSelected((prev) => {
              const next = new Set(prev);
              if (checked) next.add(String(k));
              else next.delete(String(k));
              return next;
            });
          }}
          page={page}
          pageSize={pageSize}
          total={sortedUsers.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); localStorage.setItem(PAGE_SIZE_KEY, String(n)); setPage(1); }}
          density={density}
          caption={t('users', 'Users')}
        />
      )}

      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm}
        title={confirm.title}
        message={confirm.message}
        danger={confirm.danger}
        confirmLabel={confirm.confirmLabel}
      />
      <UserFormModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSaved={async () => {
          addToast(t('userCreated', 'User created'), 'success');
          setIsAddModalOpen(false);
          fetchUsers();
        }}
      />
      <UserFormModal
        isOpen={isEditModalOpen}
        onClose={() => { setIsEditModalOpen(false); setSelectedUser(null); }}
        user={selectedUser}
        onSaved={async () => {
          addToast(t('userUpdated'), 'success');
          setIsEditModalOpen(false);
          setSelectedUser(null);
          fetchUsers();
        }}
      />
      <ExtendUserModal
        user={selectedUser}
        isOpen={isExtendModalOpen}
        onClose={() => { setIsExtendModalOpen(false); }}
        onExtend={handleExtend}
      />
      <SelectNodeForDownloadModal
        isOpen={isDownloadModalOpen}
        onClose={() => { setIsDownloadModalOpen(false); setSelectedUser(null); }}
        user={selectedUser}
      />
      <UserSessionsModal
        isOpen={isSessionsModalOpen}
        onClose={() => setIsSessionsModalOpen(false)}
        user={selectedUser}
        data={sessionDiagnostics}
        loading={sessionLoading}
        error={sessionError}
        onRefresh={() => selectedUser && handleShowSessions(selectedUser)}
        onDisconnect={handleDisconnect}
      />
      <UserDetailModal
        isOpen={isDetailModalOpen}
        onClose={() => { setIsDetailModalOpen(false); setSelectedUser(null); }}
        user={selectedUser}
        onEdit={(u) => { setIsDetailModalOpen(false); handleEdit(u); }}
        onDelete={(u) => { setIsDetailModalOpen(false); handleDelete(u); }}
        onSessions={(u) => { setIsDetailModalOpen(false); handleShowSessions(u); }}
        onExtend={(u) => { setIsDetailModalOpen(false); setSelectedUser(u); setIsExtendModalOpen(true); }}
        onDownload={(u) => { setIsDetailModalOpen(false); handleOpenDownloadModal(u); }}
        onResetUsage={(u) => { setIsDetailModalOpen(false); handleResetUsage(u); }}
        onToggleStatus={(u) => { handleToggleStatus(u); setSelectedUser((prev) => prev && prev.uuid === u.uuid ? { ...prev, is_active: !u.is_active } : prev); }}
        onCopyLink={async (u) => { const ok = await copyText(getSubscriptionLink(u)); addToast(ok ? t('linkCopied') : t('error'), ok ? 'success' : 'error'); }}
        onShowQR={handleUserClick}
        subscriptionLink={selectedUser ? getSubscriptionLink(selectedUser) : ''}
      />
    </div>
  );
};

export default UserManagement;
