import { useState, useEffect, useMemo, useCallback } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  FiDownload, FiSearch, FiPlus, FiCheck, FiWifi, FiUsers,
  FiEdit2, FiActivity, FiTrash2, FiClock, FiUserCheck, FiUserX, FiRefreshCw, FiMoreHorizontal,
} from 'react-icons/fi';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import { useTranslation } from 'react-i18next';
import { daysUntil, fmtRelative, fmtDate } from '../utils/time';
import { setDisplayTimezone } from '../utils/displayTimezone';
import { formatBytes } from '../utils/format';
import UserFormModal from '../components/UserFormModal';
import ExtendUserModal from '../components/ExtendUserModal';
import SelectNodeForDownloadModal from '../components/SelectNodeForDownloadModal';
import UserSessionsModal from '../components/UserSessionsModal';
import UserDetailModal from '../components/UserDetailModal';
import ConfirmModal from '../components/ConfirmModal';
import { Button, DataTable, EmptyState, ErrorState, PageHeader, StatCard, StatusBadge } from '../components/ui';
import './UserManagement.css';

const PAGE_SIZE_KEY = 'ovmanager-ui-users-pagesize';
const MAX_VISIBLE_TAGS = 8;
const SORT_KEY = 'ovmanager-ui-users-sort-v2';

const statusOf = (u: any) => {
  const online = u.online || Number(u.active_connections || 0) > 0;
  if (online) return 'online';
  const d = daysUntil(u.expiry_date);
  if (d < 0 || d === -Infinity) return u.is_active === false ? 'offline' : 'danger';
  if (u.is_active === false) return 'offline';
  if (d <= 7) return 'warning';
  return 'idle';
};

const statusLabel = (u: any, t: any) => {
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
  const [users, setUsers] = useState<any[]>([]);
  const [subSettings, setSubSettings] = useState<any>(null);
  const [myDefaults, setMyDefaults] = useState<any>(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isExtendModalOpen, setIsExtendModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [isSessionsModalOpen, setIsSessionsModalOpen] = useState(false);
  const [sessionDiagnostics, setSessionDiagnostics] = useState<any>(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState('');
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [selected, setSelected] = useState(() => new Set<string>());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [lastDeleted, setLastDeleted] = useState<{ uuid: string; name: string } | null>(null);
  const [rowMenu, setRowMenu] = useState<{ uuid: string; user: any; left: number; top?: number; bottom?: number } | null>(null);

  const [sort, setSort] = useState<{ key: string; dir: string }>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(SORT_KEY) || 'null');
      if (raw?.key) return raw;
    } catch { /* ignore */ }
    return { key: 'id', dir: 'desc' };
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25);

  type UserConfirm = { open: boolean; title: string; message: string; onConfirm: (() => void | Promise<void>) | null; danger: boolean; confirmLabel: string | null };
  const [confirm, setConfirm] = useState<UserConfirm>({ open: false, title: '', message: '', onConfirm: null, danger: true, confirmLabel: null });
  const openConfirm = (title: string, message: string, onConfirm: () => void | Promise<void>, danger: boolean = true, confirmLabel: string | null = null) =>
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
      if (data?.timezone) setDisplayTimezone(data.timezone);
    } catch { /* subscription links degrade to hidden, table still works */ }
  }, []);

  const fetchMyDefaults = useCallback(async () => {
    try {
      const res = await apiClient.get('/admin/me/defaults');
      const data = res.data?.data || null;
      if (data?.effective) setMyDefaults(data.effective);
    } catch { /* fall back to the global defaults below */ }
  }, []);

  const { subscribe } = useLive();
  useEffect(() => {
    const u1 = subscribe('users.changed', () => fetchUsers({ background: true }));
    const u2 = subscribe('users.created', () => fetchUsers({ background: true }));
    const u3 = subscribe('users.deleted', () => fetchUsers({ background: true }));
    const u4 = subscribe('tick', () => {});
    return () => { u1(); u2(); u3(); u4(); };
  }, [subscribe, fetchUsers]);

  useEffect(() => { fetchUsers(); fetchSubSettings(); fetchMyDefaults(); }, [fetchUsers, fetchSubSettings, fetchMyDefaults]);

  useEffect(() => {
    if (!lastDeleted) return undefined;
    const id = setTimeout(() => setLastDeleted(null), 120000);
    return () => clearTimeout(id);
  }, [lastDeleted]);

  const userStats = useMemo(() => ({
    total: users.length,
    active: users.filter((u: any) => u.is_active).length,
    online: users.filter((u: any) => u.online || Number(u.active_connections || 0) > 0).length,
    inactive: users.filter((u: any) => !u.is_active).length,
  }), [users]);

  const filterCounts = useMemo(() => {
    const c = (fn: (u: any) => boolean) => users.filter(fn).length;
    return {
      all: users.length,
      online: c((u: any) => u.online || Number(u.active_connections || 0) > 0),
      expiring: c((u: any) => { const d = daysUntil(u.expiry_date); return d >= 0 && d <= 7; }),
      quota: c((u: any) => Number(u.total) > 0 && (Number(u.used || 0) / Number(u.total)) >= 0.85),
      disabled: c((u: any) => !u.is_active),
      unlimited: c((u: any) => u.total === null || u.total === 0),
    };
  }, [users]);

  const userTags = useMemo(
    () => [...new Set(users.map((u) => u.tag).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    [users],
  );
  const tagCounts = useMemo(() => {
    const counts = new Map();
    for (const u of users) {
      if (!u.tag) continue;
      counts.set(u.tag, (counts.get(u.tag) || 0) + 1);
    }
    return counts;
  }, [users]);
  const [tagsExpanded, setTagsExpanded] = useState(false);
  const visibleTags = tagsExpanded ? userTags : userTags.slice(0, MAX_VISIBLE_TAGS);

  const searchTerm = searchParams.get('q') || '';
  const view = searchParams.get('view') || 'all';
  const patchParams = useCallback((mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  const [draft, setDraft] = useState(searchTerm);
  useEffect(() => { setDraft(searchTerm); }, [searchTerm]);
  useEffect(() => {
    if (draft === searchTerm) return undefined;
    const id = setTimeout(() => {
      setPage(1);
      patchParams((p) => { if (draft) p.set('q', draft); else p.delete('q'); });
    }, 275);
    return () => clearTimeout(id);
  }, [draft, searchTerm, patchParams]);
  const setSearchTerm = (value: string) => { setDraft(value); };
  const clearFilters = useCallback(() => {
    setDraft('');
    setPage(1);
    patchParams((p) => { p.delete('q'); p.delete('view'); });
  }, [patchParams]);
  const setView = (value: string) => { setPage(1); patchParams((p) => { if (value && value !== 'all') p.set('view', value); else p.delete('view'); }); };

  const filteredUsers = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return users.filter((user) => {
      if (term) {
        const hay = `${user.name || ''} ${user.tag || ''} ${user.owner || ''}`.toLowerCase();
        if (!hay.includes(term)) return false;
      }
      if (view === 'online' && !(user.online || Number(user.active_connections || 0) > 0)) return false;
      if (view === 'expiring') { const d = daysUntil(user.expiry_date); if (!(d >= 0 && d <= 7)) return false; }
      if (view === 'quota') { if (!(Number(user.total) > 0 && (Number(user.used || 0) / Number(user.total)) >= 0.85)) return false; }
      if (view === 'disabled' && user.is_active) return false;
      if (view === 'unlimited' && (user.total !== null && user.total !== 0)) return false;
      if (view.startsWith('tag:') && (user.tag || '') !== view.slice(4)) return false;
      return true;
    });
  }, [users, searchTerm, view]);

  const sortedUsers = useMemo(() => {
    const arr = [...filteredUsers];
    const { key, dir } = sort;
    const mul = dir === 'desc' ? -1 : 1;
    const val = (u: any) => {
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

  const onSort = useCallback((key: string) => {
    setSort((prev) => {
      const next = prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' };
      localStorage.setItem(SORT_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

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

  const getSubscriptionLink = useCallback((user: any) => {
    if (!user?.uuid || !subSettings) return '';
    const rawPrefix = subSettings.subscription_url_prefix || '';
    const rawPath = (subSettings.subscription_path || 'sub').replace(/^\/+|\/+$/g, '') || 'sub';
    if (!rawPrefix) return '';
    const prefix = rawPrefix.endsWith('/') ? rawPrefix : `${rawPrefix}/`;
    return `${prefix}${rawPath}/${user.uuid}`;
  }, [subSettings]);

  const handleToggleStatus = useCallback(async (user: any) => {
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
      const errAny = e as any;
      addToast(errAny.response?.data?.detail || t('error'), 'error');
    }
  }, [addToast, fetchUsers, t]);

  const handleDelete = useCallback((user: any) => {
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
      const errUndo = e as any;
      addToast(errUndo.response?.data?.detail || t('undoFailed', 'Undo failed — user could not be restored.'), 'error');
    }
  }, [lastDeleted, addToast, fetchUsers, t]);

  const handleExtend = useCallback(async (user: any, { days, bytes }: { days: any; bytes: any }) => {
    const res = await apiClient.post(`/users/${user.uuid}/extend`, { days, bytes });
    if (res.data?.success) {
      addToast(t('extended', 'User {{name}} extended.', { name: user.name }), 'success');
      fetchUsers({ background: true });
    } else {
      throw new Error(res.data?.msg || t('error'));
    }
  }, [addToast, fetchUsers, t]);

  const handleShowSessions = useCallback(async (user: any) => {
    setSelectedUser(user);
    setSessionLoading(true);
    setSessionError('');
    setSessionDiagnostics(null);
    setIsSessionsModalOpen(true);
    try {
      const res = await apiClient.get(`/users/${user.uuid}/sessions`);
      setSessionDiagnostics(res.data?.data || res.data);
    } catch (e) {
      const errSess = e as any;
      setSessionError(errSess.response?.data?.detail || errSess.message || t('error'));
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
      const errAny = e as any;
      addToast(errAny.response?.data?.detail || t('error'), 'error');
    }
  }, [selectedUser, addToast, t]);

  const handleEdit = useCallback((user: any) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  }, []);

  const handleOpenDownloadModal = useCallback((user: any) => {
    setSelectedUser(user);
    setIsDownloadModalOpen(true);
  }, []);

  const handleUserClick = useCallback((user: any) => {
    setSelectedUser(user);
    setIsDetailModalOpen(true);
  }, []);

  const handleResetUsage = useCallback(async (user: any) => {
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

  const runBulk = useCallback(async (op: string, label: string) => {
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

  const confirmBulk = (op: string, titleKey: string, msgKey: string, label: string) => {
    openConfirm(
      t(titleKey, label) as string,
      t(msgKey, `${label} {{count}} selected users?`, { count: selected.size }) as string,
      () => runBulk(op, label),
      op === 'delete',
      label
    );
  };

  const anySelectedDisabled = useMemo(
    () => users.some((u) => selected.has(String(u.uuid)) && u.is_active === false),
    [users, selected],
  );

  const openRowMenu = useCallback((e: ReactMouseEvent<HTMLButtonElement>, user: any) => {
    if (rowMenu?.uuid === String(user.uuid)) { setRowMenu(null); return; }
    const rect = e.currentTarget.getBoundingClientRect();
    const width = 200;
    const openUp = rect.bottom + 240 + 8 > window.innerHeight;
    setRowMenu({
      uuid: String(user.uuid),
      user,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      ...(openUp ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
    });
  }, [rowMenu]);

  useEffect(() => {
    if (!rowMenu) return undefined;
    const close = (e: Event) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.closest('.um-rowmenu-panel') || el.closest('.um-rowmenu-trigger'))) return;
      setRowMenu(null);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setRowMenu(null); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [rowMenu]);

  const columns = useMemo(() => [
    {
      key: 'name', label: t('th_username', 'Username'), sortable: true,
      render: (u: any) => (
        <button type="button" className="dt-rowlink" onClick={() => handleUserClick(u)} title={u.uuid}>
          <span className="dt-cell-main">
            <span className="dt-avatar" aria-hidden="true">{String(u.name || '?').slice(0, 1).toUpperCase()}</span>
            <span style={{ minWidth: 0 }}>
              <span className="dt-cell-title">
                {u.name}
                {u.tag && <span className="dt-tag">{u.tag}</span>}
              </span>
              <br />
              <span className="dt-cell-sub">{u.owner || '—'}</span>
            </span>
          </span>
        </button>
      ),
    },
    {
      key: 'status', label: t('th_status', 'Status'), sortable: true,
      render: (u: any) => <StatusBadge status={statusOf(u)} label={statusLabel(u, t)} />,
    },
    {
      key: 'used', label: t('th_dataUsed', 'Data used'), sortable: true,
      render: (u: any) => {
        const used = Number(u.used || 0);
        const total = u.total == null || Number(u.total) === 0 ? null : Number(u.total);
        const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
        return (
          <span className="dt-usage">
            <span className="dt-usage-bar" aria-hidden="true">
              <span className={`dt-usage-fill${pct >= 95 ? ' is-danger' : pct >= 85 ? ' is-warn' : ''}`} style={{ width: `${total ? pct : 0}%` }} />
            </span>
            <span className="dt-num">
              {formatBytes(used)}{total ? ` / ${formatBytes(total)}` : <>{' '}<span className="um-data-total">of ∞</span></>}
            </span>
          </span>
        );
      },
    },
    {
      key: 'active_connections', label: t('th_sessions', 'Sessions'), sortable: true, className: 'dt-num', hideOnMobile: true,
      render: (u: any) => `${Number(u.active_connections || 0)}/${u.max_logins === 0 ? '∞' : (u.max_logins ?? '—')}`,
    },
    {
      key: 'expiry_date', label: t('th_expiryDate', 'Expiry'), sortable: true,
      render: (u: any) => {
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
      render: (u: any) => <span className="dt-num">{u.last_online ? fmtRelative(u.last_online) : t('never', 'Never')}</span>,
    },
    {
      key: 'actions', label: t('th_actions', 'Actions'),
      render: (u: any) => (
        <span className="dt-actions" role="group" aria-label={`${u.name} ${t('actions', 'Actions')}`}>
          <button type="button" className="dt-icon-btn" title={t('rowEdit', 'Edit')} aria-label={`${t('rowEdit', 'Edit')} ${u.name}`} onClick={() => handleEdit(u)}><FiEdit2 size={15} /></button>
          <button type="button" className="dt-icon-btn is-danger" title={t('rowDelete', 'Delete')} aria-label={`${t('rowDelete', 'Delete')} ${u.name}`} onClick={() => handleDelete(u)}><FiTrash2 size={15} /></button>
          <button
            type="button"
            className="dt-icon-btn um-rowmenu-trigger"
            aria-haspopup="menu"
            aria-expanded={rowMenu?.uuid === String(u.uuid)}
            title={t('moreActions', 'More actions')}
            aria-label={`${t('moreActions', 'More actions')} ${u.name}`}
            onClick={(e) => openRowMenu(e, u)}
          >
            <FiMoreHorizontal size={16} />
          </button>
        </span>
      ),
    },
  ], [t, rowMenu, openRowMenu, handleUserClick, handleEdit, handleDelete]);

  const allPageKeys = pagedUsers.map((u) => String(u.uuid));
  const allSelected = allPageKeys.length > 0 && allPageKeys.every((k) => selected.has(k));
  const someSelected = allPageKeys.some((k) => selected.has(k));

  return (
    <div id="users-view" className="view um-page">
      <PageHeader
        title={t('users')}
        icon={<FiUsers aria-hidden="true" />}
        meta={(
          <span className="um-meta">
            <strong>{filteredUsers.length}</strong> {filteredUsers.length === 1 ? t('resultOne', 'result') : t('resultsMany', 'results')}
          </span>
        )}
        actions={(
          <Button variant="primary" icon={<FiPlus size={14} aria-hidden="true" />} onClick={() => setIsAddModalOpen(true)}>
            {t('addUser')}
          </Button>
        )}
      />

      <div className="um-stats" role="region" aria-label={t('userStats', 'User statistics')}>
        <StatCard className="um-stat" icon={<FiUsers aria-hidden="true" />} label={t('totalUsers')} value={userStats.total} tone="accent" hint={undefined} />
        <StatCard className="um-stat" icon={<FiCheck aria-hidden="true" />} label={t('activeUsers')} value={userStats.active} tone="success" hint={undefined} />
        <StatCard className="um-stat" icon={<FiWifi aria-hidden="true" />} label={t('onlineUsers')} value={userStats.online} tone="success" hint={undefined} />
        <StatCard className="um-stat" icon={<FiUserX aria-hidden="true" />} label={t('inactiveUsers')} value={userStats.inactive} tone="danger" hint={undefined} />
      </div>

      <div className="um-toolbar">
        <label className="um-search">
          <FiSearch className="um-search-icon" aria-hidden="true" />
          <input
            type="search"
            className="ui-input um-search-input"
            placeholder={t('searchByUsername')}
            value={draft}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label={t('searchByUsername')}
          />
        </label>
        <div className="um-filters" role="group" aria-label={t('userFilters', 'User filters')}>
          {[
            { id: 'all', label: t('filterAll', 'All') },
            { id: 'online', label: t('filterOnline', 'Online') },
            { id: 'expiring', label: t('filterExpiring', 'Expiring soon') },
            { id: 'quota', label: t('filterQuota', 'Near quota') },
            { id: 'disabled', label: t('filterDisabled', 'Disabled') },
            { id: 'unlimited', label: t('filterUnlimited', 'Unlimited') },
          ].map((f) => (
            <button key={f.id} type="button" className={`um-chip${view === f.id ? ' is-active' : ''}`} aria-pressed={view === f.id} onClick={() => setView(f.id)}>
              {f.label} <span className="um-chip-count">{(filterCounts as Record<string, number>)[f.id] ?? 0}</span>
            </button>
          ))}
          {visibleTags.map((tag) => (
            <button
              key={tag}
              type="button"
              className={`um-chip um-chip-tag${view === `tag:${tag}` ? ' is-active' : ''}`}
              aria-pressed={view === `tag:${tag}`}
              onClick={() => setView(`tag:${tag}`)}
              title={tag}
            >
              <span className="um-chip-label">{tag}</span> <span className="um-chip-count">{tagCounts.get(tag) ?? 0}</span>
            </button>
          ))}
          {userTags.length > MAX_VISIBLE_TAGS && (
            <button
              type="button"
              className="um-chip um-chip-more"
              aria-expanded={tagsExpanded}
              onClick={() => setTagsExpanded((v) => !v)}
            >
              {tagsExpanded
                ? t('showLess', 'Show less')
                : t('showMoreTags', '+{{count}} more', { count: userTags.length - MAX_VISIBLE_TAGS })}
            </button>
          )}
          {(searchTerm || view !== 'all') && (
            <button type="button" className="um-clear" onClick={clearFilters}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

      {lastDeleted && (
        <div className="um-bulkbar" role="status" aria-live="polite">
          <span>{t('userDeletedUndo', 'User {{name}} deleted', { name: lastDeleted.name })}</span>
          <Button size="sm" onClick={handleUndoDelete}>{t('undo', 'Undo')}</Button>
          <Button size="sm" variant="ghost" onClick={() => setLastDeleted(null)} aria-label={t('dismiss', 'Dismiss')}>✕</Button>
        </div>
      )}

      {selected.size > 0 && (
        <div className="um-bulkbar" role="toolbar" aria-label={t('bulkActions', 'Bulk actions')}>
          <strong>{t('selectedCount', '{{count}} selected', { count: selected.size })}</strong>
          <Button size="sm" disabled={bulkBusy || anySelectedDisabled} icon={<FiClock size={13} aria-hidden="true" />} onClick={() => confirmBulk('extend30', 'extend', 'confirmBulkExtend', t('extend30d', 'Extend +30 days'))}>{t('extend30d', 'Extend +30 days')}</Button>
          <Button size="sm" disabled={bulkBusy} icon={<FiUserCheck size={13} aria-hidden="true" />} onClick={() => confirmBulk('enable', 'enableUsers', 'confirmBulkEnable', t('enable', 'Enable'))}>{t('enable', 'Enable')}</Button>
          <Button size="sm" disabled={bulkBusy} icon={<FiUserX size={13} aria-hidden="true" />} onClick={() => confirmBulk('disable', 'disableUsers', 'confirmBulkDisable', t('disable', 'Disable'))}>{t('disable', 'Disable')}</Button>
          <Button size="sm" disabled={bulkBusy} icon={<FiRefreshCw size={13} aria-hidden="true" />} onClick={() => confirmBulk('reset', 'resetUsage', 'confirmBulkReset', t('resetUsageButton', 'Reset usage'))}>{t('resetUsageButton', 'Reset usage')}</Button>
          <Button size="sm" variant="danger" disabled={bulkBusy} icon={<FiTrash2 size={13} aria-hidden="true" />} onClick={() => confirmBulk('delete', 'deleteUsers', 'confirmBulkDelete', t('delete', 'Delete'))}>{t('delete', 'Delete')}</Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>{t('clear', 'Clear')}</Button>
        </div>
      )}

      {isLoading && users.length === 0 ? (
        <DataTable columns={columns} rows={[]} loading />
      ) : loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchUsers()} retryLabel={t('retry')} />
      ) : users.length === 0 ? (
        <EmptyState title={t('noUsersTitle')} description={t('noUsersBody')} actionLabel={t('addNewUser')} onAction={() => setIsAddModalOpen(true)} />
      ) : filteredUsers.length === 0 ? (
        <EmptyState
          title={t('noMatchesTitle', 'No matching users')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={clearFilters}
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
          caption={t('users', 'Users')}
        />
      )}

      {rowMenu && (
        <div
          className="um-rowmenu-panel"
          role="menu"
          aria-label={t('moreActions', 'More actions')}
          style={{ left: rowMenu.left, top: rowMenu.top, bottom: rowMenu.bottom }}
        >
          <button type="button" role="menuitem" className="um-rowmenu-item" onClick={() => { setRowMenu(null); handleOpenDownloadModal(rowMenu.user); }}><FiDownload size={14} aria-hidden="true" /> {t('downloadConfig', 'Get Config')}</button>
          <button type="button" role="menuitem" className="um-rowmenu-item" onClick={() => { setRowMenu(null); setSelectedUser(rowMenu.user); setIsExtendModalOpen(true); }}><FiClock size={14} aria-hidden="true" /> {t('extend', 'Extend')}</button>
          <button type="button" role="menuitem" className="um-rowmenu-item" onClick={() => { setRowMenu(null); handleShowSessions(rowMenu.user); }}><FiActivity size={14} aria-hidden="true" /> {t('rowSessions', 'Sessions')}</button>
          <button type="button" role="menuitem" className="um-rowmenu-item" onClick={() => { setRowMenu(null); handleToggleStatus(rowMenu.user); }}>
            {rowMenu.user.is_active ? <FiUserX size={14} aria-hidden="true" /> : <FiUserCheck size={14} aria-hidden="true" />} {rowMenu.user.is_active ? t('disableUser', 'Disable') : t('enableUser', 'Enable')}
          </button>
          <button type="button" role="menuitem" className="um-rowmenu-item" onClick={() => { setRowMenu(null); handleResetUsage(rowMenu.user); }}><FiRefreshCw size={14} aria-hidden="true" /> {t('resetUsageButton', 'Reset usage')}</button>
        </div>
      )}

      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm as () => void}
        title={confirm.title}
        message={confirm.message}
        danger={confirm.danger}
        confirmLabel={confirm.confirmLabel ?? undefined}
      />
      <UserFormModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        user={null}
        onSaved={async () => {
          addToast(t('userCreated', 'User created'), 'success');
          fetchUsers();
        }}
        defaults={{
          days: myDefaults?.days ?? subSettings?.default_days ?? 30,
          trafficGb: myDefaults?.traffic_gb ?? subSettings?.default_traffic_gb ?? '',
          maxLogins: myDefaults?.max_users ?? subSettings?.default_max_users ?? 1,
        }}
        linkForUser={getSubscriptionLink}
        onDownloadUser={handleOpenDownloadModal}
      />
      <UserFormModal
        isOpen={isEditModalOpen}
        onClose={() => { setIsEditModalOpen(false); setSelectedUser(null); }}
        user={selectedUser}
        defaults={undefined}
        linkForUser={undefined}
        onDownloadUser={undefined}
        onSaved={async () => {
          addToast(t('userUpdated', 'User updated'), 'success');
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
        onEdit={(u: any) => { setIsDetailModalOpen(false); handleEdit(u); }}
        onDelete={(u: any) => { setIsDetailModalOpen(false); handleDelete(u); }}
        onSessions={(u: any) => { setIsDetailModalOpen(false); handleShowSessions(u); }}
        onExtend={(u: any) => { setIsDetailModalOpen(false); setSelectedUser(u); setIsExtendModalOpen(true); }}
        onDownload={(u: any) => { setIsDetailModalOpen(false); handleOpenDownloadModal(u); }}
        onResetUsage={(u: any) => { setIsDetailModalOpen(false); handleResetUsage(u); }}
        onToggleStatus={(u: any) => { handleToggleStatus(u); setSelectedUser((prev: any) => prev && prev.uuid === u.uuid ? { ...prev, is_active: !u.is_active } : prev); }}
        subscriptionLink={selectedUser ? getSubscriptionLink(selectedUser) : ''}
      />
    </div>
  );
};

export default UserManagement;
