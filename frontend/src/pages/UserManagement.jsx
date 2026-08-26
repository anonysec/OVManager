import { useState, useEffect, useMemo, useRef, useDeferredValue } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FiDownload, FiClock, FiZap, FiTrash2 } from 'react-icons/fi';
import apiClient from '../services/api';
import { getPanelOrigin } from '../utils/panelUrl';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import UserTable from '../components/UserTable';
import AddUserModal from '../components/AddUserModal';
import EditUserModal from '../components/EditUserModal';
import SelectNodeForDownloadModal from '../components/SelectNodeForDownloadModal';
import UserSessionsModal from '../components/UserSessionsModal';
import UserDetailModal from '../components/UserDetailModal';
import ConfirmModal from '../components/ConfirmModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import { SkeletonTable } from '../components/ui/Skeleton';
import { FiSearch, FiPlus } from 'react-icons/fi';
import { BsPersonFill, BsPersonCheckFill, BsPersonXFill, BsPersonPlusFill } from 'react-icons/bs';
import { useTranslation } from 'react-i18next';
import { daysUntil } from '../utils/time';
import { copyText } from '../utils/clipboard';

const UserManagement = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [users, setUsers] = useState([]);
  const [subscriptionSettings, setSubscriptionSettings] = useState(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [isSessionsModalOpen, setIsSessionsModalOpen] = useState(false);
  const [sessionDiagnostics, setSessionDiagnostics] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState('');
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const { t } = useTranslation();
  const { addToast } = useToast();

  const [searchTerm, setSearchTerm] = useState('');
  const [view, setView] = useState('all');
  const [selected, setSelected] = useState([]);
  const [sort, setSort] = useState({ key: 'name', dir: 'asc' });
  const [_bulkBusy, setBulkBusy] = useState(false);
  const [loadError, setLoadError] = useState(false);
  // First-load vs background refresh. The table used to receive a hardcoded
  // isLoading={false}, so its skeleton could never render and the list simply
  // popped in. Tracking this properly also lets SSE refreshes stay silent.
  const [isLoading, setIsLoading] = useState(true);
  const [undo, setUndo] = useState(null); // { user, ts } for undo-delete toast
  const [density, setDensity] = useState(() => localStorage.getItem('ovmanager-ui-density') === 'compact' ? 'compact' : 'comfortable');

  // ── ConfirmModal state ────────────────────────────────────────────────
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null, danger: true });

  const openConfirm = (title, message, onConfirm, danger = true) =>
    setConfirm({ open: true, title, message, onConfirm, danger });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  // ── Data fetching ─────────────────────────────────────────────────────
  const fetchUsers = async ({ background = false } = {}) => {
    setLoadError(false);
    // Only show the skeleton when there is nothing on screen. A background
    // refresh keeps the current rows so the table never flashes mid-read.
    if (!background) setIsLoading((prev) => (users.length === 0 ? true : prev));
    try {
      const response = await apiClient.get('/users/');
      const raw = response.data?.data;
      const list = Array.isArray(raw) ? raw : (raw?.users || []);
      if (response.data.success) {
        setUsers(list.slice().reverse());
      } else {
        setUsers([]);
      }
    } catch (error) {
      console.error('Error fetching users:', error);
      setUsers([]);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchSubscriptionSettings = async () => {
    try {
      const response = await apiClient.get('/server/settings');
      if (response.data.success && response.data.data) {
        setSubscriptionSettings(response.data.data);
      }
    } catch (error) {
      console.error('Error fetching subscription settings:', error);
    }
  };

  // ── Live updates ──────────────────────────────────────────────────────
  // Any server-side user change (add/edit/delete by ANY admin, usage sync,
  // expiry enforcement, connection counts) bumps refreshTick via SSE → the
  // table refreshes itself without polling or manual reloads.
  const { refreshTick } = useLive();
  const fetchUsersRef = useRef(fetchUsers);
  useEffect(() => {
    fetchUsersRef.current = fetchUsers;
  });
  // Runs on mount (initial load) and on every live event thereafter.
  useEffect(() => {
    // refreshTick starts at 0 on mount: that first run is the real initial
    // load, every later tick is a background SSE refresh.
    fetchUsersRef.current({ background: refreshTick > 0 });
  }, [refreshTick]);

  useEffect(() => {
    fetchSubscriptionSettings();
  }, []);

  // Declared above the deep-link effect that calls it: a `const` referenced
  // before its declaration only works because effects run after the body, and
  // it stops updating correctly if the value ever changes.
  const handleEdit = (user) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  };

  useEffect(() => {
    const userId = searchParams.get('user');
    if (!userId) return;
    const u = users.find((x) => x.uuid === userId);
    if (u) {
      handleEdit(u);
      searchParams.delete('user');
      setSearchParams(searchParams, { replace: true });
    }
  }, [users, searchParams, setSearchParams]);

  // ── Derived stats ─────────────────────────────────────────────────────
  const userStats = useMemo(() => {
    const activeUsersCount = users.filter((user) => user.is_active).length;
    const onlineUsersCount = users.filter((user) => user.online || Number(user.active_connections || 0) > 0).length;
    return { total: users.length, active: activeUsersCount, inactive: users.length - activeUsersCount, online: onlineUsersCount };
  }, [users]);

  // ── Filter chip counts ────────────────────────────────────────────────
  const filterCounts = useMemo(() => {
    const c = (fn) => users.filter(fn).length;
    return {
      all: users.length,
      online: c((u) => u.online || Number(u.active_connections || 0) > 0),
      expiring: c((u) => { const d = daysUntil(u.expiry_date); return d >= 0 && d <= 7; }),
      quota: c((u) => Number(u.total) > 0 && (Number(u.used || 0) / Number(u.total)) >= 0.85),
      disabled: c((u) => !u.is_active),
      unlimited: c((u) => u.total === null || u.total === 0),
    };
  }, [users]);

  // ── Filter + sort ─────────────────────────────────────────────────────
  // The filter+sort below walks every user on each keystroke. Deferring the
  // term lets React paint the typed character immediately and recompute the
  // list at lower priority, interrupting that work if another key arrives.
  // Preferred over a debounce: no arbitrary delay, no stale timer to clear,
  // and the list still settles on the final value.
  const deferredSearch = useDeferredValue(searchTerm);
  const isSearchPending = deferredSearch !== searchTerm;

  const filteredUsers = useMemo(() => {
    const term = deferredSearch.trim().toLowerCase();
    let list = users.filter((user) => {
      if (!String(user.name || '').toLowerCase().includes(term)) return false;
      if (view === 'online') return user.online || Number(user.active_connections || 0) > 0;
      if (view === 'inactive') return !user.is_active;
      if (view === 'expiring') return daysUntil(user.expiry_date) >= 0 && daysUntil(user.expiry_date) <= 7;
      if (view === 'quota') return Number(user.total) > 0 && (Number(user.used || 0) / Number(user.total)) >= 0.85;
      if (view === 'disabled') return !user.is_active;
      if (view === 'unlimited') return user.total === null || user.total === 0;
      return true;
    });
    const { key, dir } = sort;
    const mul = dir === 'asc' ? 1 : -1;
    list = list.slice().sort((a, b) => {
      let av, bv;
      if (key === 'name' || key === 'owner') {
        av = (a[key] || '').toString().toLowerCase();
        bv = (b[key] || '').toString().toLowerCase();
      } else if (key === 'expiry_date' || key === 'last_online') {
        av = a[key] ? new Date(a[key]).getTime() : (key === 'expiry_date' ? Infinity : 0);
        bv = b[key] ? new Date(b[key]).getTime() : (key === 'expiry_date' ? Infinity : 0);
      } else if (key === 'total') {
        av = Number(a.total ?? 0); bv = Number(b.total ?? 0);
      } else if (key === 'max_logins') {
        av = Number(a.max_logins ?? 0); bv = Number(b.max_logins ?? 0);
      } else {
        av = a[key]; bv = b[key];
      }
      if (av < bv) return -1 * mul;
      if (av > bv) return 1 * mul;
      return 0;
    });
    return list;
  }, [users, deferredSearch, view, sort]);

  const handleSort = (key) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));

  const handleSelect = (uuid) =>
    setSelected((s) => (s.includes(uuid) ? s.filter((x) => x !== uuid) : [...s, uuid]));

  const handleSelectAll = (checked) =>
    setSelected(checked ? filteredUsers.map((u) => u.uuid) : []);

  // ── Actions (all use ConfirmModal, no window.confirm) ─────────────────
  const handleDelete = (user) => {
    openConfirm(
      t('rowDelete', 'Delete User'),
      t('confirmDeleteUser', { name: user.name }, `Delete user "${user.name}"?`),
      async () => {
        try {
          await apiClient.delete(`/users/${user.uuid}`);
          addToast(t('userDeleted', { name: user.name }, `User "${user.name}" deleted.`), 'success');
          setSelected((s) => s.filter((x) => x !== user.uuid));
          setUndo({ user, ts: Date.now() });
          fetchUsers();
        } catch {
          // t(key, defaultValue, options) — the default and options were
          // swapped, so {{name}} never interpolated.
          addToast(t('userDeleteError', `Failed to delete "${user.name}".`, { name: user.name }), 'error');
        }
      }
    );
  };

  const handleBulkDelete = (uuids) => {
    openConfirm(
      t('deleteSelected', 'Delete Selected'),
      t('confirmBulkDelete', { count: uuids.length }, `Delete ${uuids.length} selected users?`),
      async () => {
        setBulkBusy(true);
        try {
          const results = await Promise.allSettled(uuids.map((uuid) => apiClient.delete(`/users/${uuid}`)));
          const failed = results.filter((r) => r.status === 'rejected' || r.value?.data?.success === false);
          const succeeded = uuids.length - failed.length;
          setSelected([]);
          fetchUsers();
          if (failed.length > 0) {
            addToast(t('bulkDeletePartial', { succeeded, failed: failed.length, total: uuids.length },
              `Deleted ${succeeded} of ${uuids.length} users. ${failed.length} failed (check node connectivity).`), 'warning');
          } else {
            addToast(t('bulkDeleteSuccess', { count: succeeded }, `Deleted ${succeeded} users.`), 'success');
          }
        } finally {
          setBulkBusy(false);
        }
      }
    );
  };

  // ── Undo delete ────────────────────────────────────────────────────────
  // The countdown is driven by a clock held in state. Reading Date.now()
  // during render is impure and, with no timer, the number never moved — the
  // toast sat on its initial value until it disappeared.
  const [undoNow, setUndoNow] = useState(0);
  useEffect(() => {
    if (!undo) return;
    const tick = () => setUndoNow(Date.now());
    const immediate = setTimeout(tick, 0);
    const interval = setInterval(tick, 1000);
    const hide = setTimeout(() => setUndo(null), 6000);
    return () => {
      clearTimeout(immediate);
      clearInterval(interval);
      clearTimeout(hide);
    };
  }, [undo]);
  const undoSecondsLeft = undo ? Math.min(6, Math.max(0, Math.ceil((6000 - (undoNow - undo.ts)) / 1000))) : 0;

  const handleUndoRestore = async () => {
    if (!undo) return;
    const u = undo.user;
    setUndo(null);
    try {
      await apiClient.post(`/users/${u.uuid}/restore`);
      addToast(t('userRestored', { name: u.name }, `User "${u.name}" restored.`), 'success');
    } catch {
      addToast(t('undoFailed', 'Undo failed — user could not be restored.'), 'error');
    }
    fetchUsers();
  };

  // ── Bulk extend / add traffic ─────────────────────────────────────────
  const handleBulkAdjust = async (action, days = 0, gb = 0) => {
    if (!selected.length) return;
    setBulkBusy(true);
    try {
      const res = await apiClient.post('/users/bulk', {
        action,
        uuids: selected,
        days,
        bytes: gb * 1024 * 1024 * 1024,
      });
      if (res.data?.success) {
        addToast(res.data.msg || `${selected.length} user(s) updated`, 'success');
        setSelected([]);
        fetchUsers();
      } else {
        addToast(res.data?.msg || 'Bulk update failed', 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || e.response?.data?.msg || 'Bulk update failed', 'error');
    } finally { setBulkBusy(false); }
  };

  const handleExtendSingle = async (user) => {
    try {
      const res = await apiClient.post('/users/bulk', { action: 'extend', uuids: [user.uuid], days: 30, bytes: 0 });
      addToast(res.data?.success ? t('extendedDays', 'Extended {{name}} by 30 days', { name: user.name }) : (res.data?.msg || 'Failed'), res.data?.success ? 'success' : 'error');
      fetchUsers();
    } catch { addToast(t('error', 'Error'), 'error'); }
  };

  const handleDisconnectUserQuick = async (user) => {
    try {
      await apiClient.post(`/users/${user.uuid}/disconnect`);
      addToast(t('disconnected', 'Disconnect requested'), 'success');
    } catch { addToast(t('error', 'Error'), 'error'); }
  };

  // ── CSV export ────────────────────────────────────────────────────────
  const handleExportCsv = () => {
    const esc = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const head = ['name', 'status', 'used_bytes', 'total_bytes', 'max_logins', 'expiry_date', 'last_online', 'owner'];
    const rows = filteredUsers.map((u) => [
      u.name, u.is_active ? 'active' : 'inactive', u.used || 0, u.total ?? '', u.max_logins ?? '', u.expiry_date || '', u.last_online || '', u.owner || '',
    ]);
    const csv = [head, ...rows].map((r) => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `ovmanager-users-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };

  // ── Density ───────────────────────────────────────────────────────────
  const applyDensity = (d) => { setDensity(d); localStorage.setItem('ovmanager-ui-density', d); window.dispatchEvent(new Event('ovmanager-ui-prefs')); };

  const handleToggleStatus = (user) => {
    const newStatus = !user.is_active;
    const action = newStatus ? t('enableUser', 'Enable') : t('disableUser', 'Disable');
    openConfirm(
      action,
      t('confirmToggleStatus', { name: user.name, action: action.toLowerCase() },
        `${action} user "${user.name}"?`),
      async () => {
        try {
          const response = await apiClient.put(`/users/${user.uuid}/status`, { name: user.name, status: newStatus });
          if (response.data.success) {
            addToast(t('userStatusChanged', { name: user.name, action: action.toLowerCase() },
              `User "${user.name}" ${action.toLowerCase()}d.`), 'success');
            fetchUsers();
          } else {
            addToast(t('userStatusFailed', { name: user.name, action: action.toLowerCase() },
              `Failed to ${action.toLowerCase()} "${user.name}".`), 'error');
          }
        } catch {
          addToast(t('userStatusFailed', { name: user.name, action: action.toLowerCase() }), 'error');
        }
      },
      !newStatus // danger = deactivating
    );
  };

  const handleResetUsage = (user) => {
    openConfirm(
      t('resetUsageButton', 'Reset Usage'),
      `Reset all usage data for "${user.name}"? This cannot be undone.`,
      async () => {
        try {
          const response = await apiClient.post(`/users/${user.uuid}/reset-usage`);
          if (response.data.success) {
            addToast(`Usage for ${user.name} has been reset.`, 'success');
            fetchUsers();
          } else {
            addToast(`Failed to reset usage for ${user.name}.`, 'error');
          }
        } catch {
          addToast('Error resetting usage.', 'error');
        }
      }
    );
  };

  const handleDisconnectUser = () => {
    if (!selectedUser?.uuid) return;
    openConfirm(
      t('disconnect', 'Disconnect Sessions'),
      `Disconnect all active sessions for "${selectedUser.name}"?`,
      async () => {
        setSessionLoading(true);
        setSessionError('');
        try {
          const response = await apiClient.post(`/users/${selectedUser.uuid}/disconnect`);
          if (!response.data.success) setSessionError(response.data.msg || 'Disconnect failed.');
          await fetchSessionDiagnostics(selectedUser);
        } catch (err) {
          const detail = err.response?.data?.detail;
          setSessionError(
            Array.isArray(detail) ? detail.map((d) => d.msg || JSON.stringify(d)).join(', ')
              : typeof detail === 'object' && detail !== null ? JSON.stringify(detail)
                : detail || 'Disconnect failed.'
          );
        } finally {
          setSessionLoading(false);
        }
      }
    );
  };

  // ── Session diagnostics ───────────────────────────────────────────────
  const fetchSessionDiagnostics = async (user) => {
    if (!user?.uuid) return;
    setSessionLoading(true);
    setSessionError('');
    try {
      const response = await apiClient.get(`/maintenance/login-diagnostics/${encodeURIComponent(user.name)}?hours=8`);
      if (response.data.success) {
        setSessionDiagnostics(response.data.data);
      } else {
        setSessionError(response.data.msg || 'Failed to load session diagnostics.');
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      setSessionError(
        Array.isArray(detail) ? detail.map((d) => d.msg || JSON.stringify(d)).join(', ')
          : typeof detail === 'object' && detail !== null ? JSON.stringify(detail)
            : detail || 'Failed to load session diagnostics.'
      );
    } finally {
      setSessionLoading(false);
    }
  };

  const handleShowSessions = (user) => {
    setSelectedUser(user);
    setSessionDiagnostics(null);
    setIsSessionsModalOpen(true);
    fetchSessionDiagnostics(user);
  };

  // ── CRUD helpers ──────────────────────────────────────────────────────
  const handleOpenDownloadModal = (user) => { setSelectedUser(user); setIsDownloadModalOpen(true); };
  const handleUserAdded = () => { setIsAddModalOpen(false); addToast('User created successfully.', 'success'); fetchUsers(); };
  const handleUserClick = (user) => { setSelectedUser(user); setIsDetailModalOpen(true); };
  const handleUserUpdated = () => { setIsEditModalOpen(false); setSelectedUser(null); addToast('User updated successfully.', 'success'); fetchUsers(); };

  const getSubscriptionLink = (user) => {
    if (!user?.uuid) return '';
    const base = getPanelOrigin();
    let prefix = subscriptionSettings?.subscription_url_prefix?.trim();
    let path = (subscriptionSettings?.subscription_path || '').trim();
    if (!prefix) prefix = `${base}/sub/`;
    if (!prefix.endsWith('/')) prefix += '/';
    if (path.startsWith('/')) path = path.slice(1);
    if (path && !path.endsWith('/')) path += '/';
    return `${prefix}${path}${user.uuid}`;
  };

  return (
    <div id="users-view" className="view">
      <div className="view-header">
        <h2>{t('users')}</h2>
        <div className="view-header-actions">
          <button type="button" onClick={handleExportCsv} className="btn btn-secondary export-btn" aria-label={t('exportCsv', 'Export CSV')} title={t('exportCsv', 'Export CSV')}>
            <FiDownload aria-hidden="true" />
            <span>{t('exportCsv', 'CSV')}</span>
          </button>
          <button type="button" onClick={() => setIsAddModalOpen(true)} className="btn" aria-label={t('addNewUser')}>
            <FiPlus aria-hidden="true" />
            <span>{t('addNewUser')}</span>
          </button>
        </div>
      </div>

      <div className="user-stats-row">
        <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
          <span className="us-ico"><BsPersonFill /></span>
          <span className="us-body"><span className="us-label">{t('totalUsers')}</span><span className="us-value">{userStats.total}</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#43a047' }}>
          <span className="us-ico"><BsPersonCheckFill /></span>
          <span className="us-body"><span className="us-label">{t('activeUsers')}</span><span className="us-value">{userStats.active}</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#66bb6a' }}>
          <span className="us-ico"><BsPersonPlusFill /></span>
          <span className="us-body"><span className="us-label">{t('onlineUsers')}</span><span className="us-value">{userStats.online}</span></span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#e53935' }}>
          <span className="us-ico"><BsPersonXFill /></span>
          <span className="us-body"><span className="us-label">{t('inactiveUsers')}</span><span className="us-value">{userStats.inactive}</span></span>
        </div>
      </div>

      <div className="search-with-filters">
        <label className="search-field" style={{ flex: 1, maxWidth: 380 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input type="search" placeholder={t('searchByUsername')} value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="search-input" aria-label="Search users by username" />
        </label>
        <div className="density-toggle" role="group" aria-label={t('density', 'Density')}>
          <button type="button" className={density === 'comfortable' ? 'active' : ''} onClick={() => applyDensity('comfortable')}>{t('densityComfort', 'Comfort')}</button>
          <button type="button" className={density === 'compact' ? 'active' : ''} onClick={() => applyDensity('compact')}>{t('densityCompact', 'Compact')}</button>
        </div>
        <div
          className={`results-meta${isSearchPending ? ' is-stale' : ''}`}
          aria-live="polite"
          aria-busy={isSearchPending}
        >
          <strong>{filteredUsers.length}</strong> {t('results', 'results')}
          {(searchTerm || view !== 'all') && (
            <button type="button" className="toolbar-clear" onClick={() => { setSearchTerm(''); setView('all'); }}>{t('clear', 'Clear')}</button>
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
          <button
            key={f.id}
            type="button"
            className={`filter-chip${view === f.id ? ' active' : ''}`}
            onClick={() => setView(f.id)}
          >
            {f.label} <span className="count">{filterCounts[f.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {selected.length > 0 && (
        <div className="bulk-toolbar">
          <b>{t('selectedCount', '{{count}} selected', { count: selected.length })}</b>
          <span className="sp" />
          <button type="button" className="btn btn-sm" onClick={() => handleBulkAdjust('extend', 30, 0)}><FiClock size={12} /> +30 {t('daysUnit', 'days')}</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => handleBulkAdjust('add-traffic', 0, 10)}><FiZap size={12} /> +10 GB</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => handleBulkDelete(selected)}><FiTrash2 size={12} /> {t('delete', 'Delete')}</button>
        </div>
      )}

      {/* Order matters: loading is checked before empty, otherwise the very
          first render (users still []) short-circuits to the empty state and
          the skeleton never appears. */}
      {isLoading && users.length === 0 ? (
        <SkeletonTable rows={8} cols={9} label={t('loading', 'Loading…')} />
      ) : loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchUsers()} retryLabel={t('retry')} />
      ) : users.length === 0 ? (
        <EmptyState title={t('noUsersTitle')} description={t('noUsersBody')} actionLabel={t('addNewUser')} onAction={() => setIsAddModalOpen(true)} />
      ) : filteredUsers.length === 0 ? (
        /* Filtered to nothing is a different situation from having no users:
           offering "add your first user" here would be wrong and confusing. */
        <EmptyState
          title={t('noMatchesTitle', 'No matching users')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={() => { setSearchTerm(''); setView('all'); }}
        />
      ) : (
        <UserTable
          users={filteredUsers}
          isLoading={isLoading}
          onUserClick={handleUserClick}
          onDelete={handleDelete}
          onSessions={handleShowSessions}
          onBulkDelete={handleBulkDelete}
          selected={selected}
          onSelect={handleSelect}
          onSelectAll={handleSelectAll}
          sort={sort}
          onSort={handleSort}
          onDownload={handleOpenDownloadModal}
          onEdit={handleEdit}
          onToggleStatus={handleToggleStatus}
          onResetUsage={handleResetUsage}
          onExtend={handleExtendSingle}
          onDisconnect={handleDisconnectUserQuick}
          onCopyLink={async (u) => { await copyText(getSubscriptionLink(u)); addToast(t('linkCopied', 'Subscription link copied'), 'success'); }}
          onShowQR={handleUserClick}
          subscriptionLink={(u) => getSubscriptionLink(u)}
          density={density}
        />
      )}

      {/* ── Modals ── */}
      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm || (() => {})}
        title={confirm.title}
        message={confirm.message}
        danger={confirm.danger}
        confirmLabel={confirm.danger !== false ? t('deleteButton', 'Delete') : t('save', 'Confirm')}
        cancelLabel={t('cancelButton', 'Cancel')}
      />
      {isDetailModalOpen && (
        <UserDetailModal isOpen={isDetailModalOpen} user={selectedUser} subscriptionLink={selectedUser ? getSubscriptionLink(selectedUser) : ''} onClose={() => setIsDetailModalOpen(false)} onEdit={handleEdit} onSessions={handleShowSessions} onDownload={handleOpenDownloadModal} onCopyId={(u) => copyText(u.uuid || '')} onToggleStatus={handleToggleStatus} />
      )}
      {isAddModalOpen && (
        <AddUserModal isOpen={isAddModalOpen} onClose={() => setIsAddModalOpen(false)} onUserAdded={handleUserAdded} />
      )}
      {isEditModalOpen && (
        <EditUserModal isOpen={isEditModalOpen} user={selectedUser} onClose={() => setIsEditModalOpen(false)} onUserUpdated={handleUserUpdated} />
      )}
      {isDownloadModalOpen && (
        <SelectNodeForDownloadModal isOpen={isDownloadModalOpen} user={selectedUser} onClose={() => setIsDownloadModalOpen(false)} />
      )}
      {isSessionsModalOpen && (
        <UserSessionsModal isOpen={isSessionsModalOpen} user={selectedUser} data={sessionDiagnostics} loading={sessionLoading} error={sessionError} onClose={() => setIsSessionsModalOpen(false)} onRefresh={() => fetchSessionDiagnostics(selectedUser)} onDisconnect={handleDisconnectUser} />
      )}

      {undo && (
        <div className="undo-toast" role="status">
          <span className="dot" aria-hidden="true" />
          {t('userDeletedUndo', 'User {{name}} deleted', { name: undo.user.name })}
          <button type="button" onClick={handleUndoRestore}>{t('undo', 'Undo')}</button>
          <span className="tick">{undoSecondsLeft}s</span>
        </div>
      )}
    </div>
  );
};

export default UserManagement;
