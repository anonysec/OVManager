import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FiDownload, FiSearch, FiPlus, FiCheck, FiWifi, FiX } from 'react-icons/fi';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import { useTranslation } from 'react-i18next';
import { daysUntil } from '../utils/time';
import { copyText } from '../utils/clipboard';
import AddUserModal from '../components/AddUserModal';
import EditUserModal from '../components/EditUserModal';
import SelectNodeForDownloadModal from '../components/SelectNodeForDownloadModal';
import UserSessionsModal from '../components/UserSessionsModal';
import UserDetailModal from '../components/UserDetailModal';
import ConfirmModal from '../components/ConfirmModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';

const UserManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [users, setUsers] = useState([]);
  const [subscriptionSettings] = useState(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDownloadModalOpen, setIsDownloadModalOpen] = useState(false);
  const [isSessionsModalOpen, setIsSessionsModalOpen] = useState(false);
  const [sessionDiagnostics, setSessionDiagnostics] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState('');
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // ── ConfirmModal state ────────────────────────────────────────────────
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null, danger: true, confirmLabel: null });
  const openConfirm = (title, message, onConfirm, danger = true, confirmLabel = null) =>
    setConfirm({ open: true, title, message, onConfirm, danger, confirmLabel });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  // ── Data fetching ─────────────────────────────────────────────────────
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

  // Live updates: users
  const { subscribe, unsubscribe } = useLive();
  useEffect(() => {
    const u1 = subscribe('users.changed', () => fetchUsers({ background: true }));
    const u2 = subscribe('users.created', () => fetchUsers({ background: true }));
    const u3 = subscribe('users.deleted', () => fetchUsers({ background: true }));
    return () => { u1(); u2(); u3(); };
  }, [subscribe, unsubscribe, fetchUsers]);

  // Initial load
  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  // ── Derived stats ─────────────────────────────────────────────────────
  const userStats = useMemo(() => ({
    total: users.length,
    active: users.filter(u => u.is_active).length,
    online: users.filter(u => u.online || Number(u.active_connections || 0) > 0).length,
    inactive: users.filter(u => !u.is_active).length,
  }), [users]);

  // ── Filter chip counts ────────────────────────────────────────────────
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

  // ── Filter state (URL-synced) ────────────────────────────────────────
  const searchTerm = searchParams.get('q') || '';
  const view = searchParams.get('view') || 'all';
  const patchParams = useCallback((mutate) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  const setSearchTerm = (value) => patchParams((p) => { if (value) p.set('q', value); else p.delete('q'); });
  const setView = (value) => patchParams((p) => { if (value && value !== 'all') p.set('view', value); else p.delete('view'); });

  // ── Filter + sort ─────────────────────────────────────────────────────
  const filteredUsers = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return users.filter((user) => {
      if (!String(user.name || '').toLowerCase().includes(term)) return false;
      if (view === 'online' && !(user.online || Number(user.active_connections || 0) > 0)) return false;
      if (view === 'expiring') { const d = daysUntil(user.expiry_date); if (!(d >= 0 && d <= 7)) return false; }
      if (view === 'quota') { if (!(Number(user.total) > 0 && (Number(user.used || 0) / Number(user.total)) >= 0.85)) return false; }
      if (view === 'disabled' && user.is_active) return false;
      if (view === 'unlimited' && (user.total !== null && user.total !== 0)) return false;
      return true;
    });
  }, [users, searchTerm, view]);

  // ── Handlers ──────────────────────────────────────────────────────────
  const getSubscriptionLink = useCallback((user) => {
    if (!subscriptionSettings) return '';
    const proto = subscriptionSettings.use_https ? 'https' : 'http';
    return `${proto}://${subscriptionSettings.domain}:${subscriptionSettings.port}/${subscriptionSettings.prefix}/${user.name}`;
  }, [subscriptionSettings]);

  const handleUserClick = useCallback((user) => {
    setSelectedUser(user);
    setIsDetailModalOpen(true);
  }, []);

  const handleDelete = useCallback((user) => {
    openConfirm(
      t('deleteUser', 'Delete user'),
      t('confirmDelete', 'Delete {{name}} and all their data?', { name: user.name }),
      async () => {
        try {
          const res = await apiClient.delete(`/users/${user.uuid}`);
          addToast(res.data?.success ? t('deleted', 'Deleted') : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          fetchUsers();
        } catch { addToast(t('error'), 'error'); }
      },
      true,
      t('deleteUser')
    );
  }, [addToast, fetchUsers, t]);

  const handleShowSessions = useCallback(async (user) => {
    setSessionLoading(true);
    setSessionError('');
    setSessionDiagnostics(null);
    try {
      const res = await apiClient.get(`/users/${user.uuid}/sessions`);
      setSessionDiagnostics(res.data);
      setIsSessionsModalOpen(true);
    } catch (e) {
      setSessionError(e.message || t('error'));
    } finally {
      setSessionLoading(false);
    }
  }, [t]);

  const handleEdit = useCallback((user) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  }, []);

  const handleExtendSingle = useCallback((user) => {
    openConfirm(
      t('extend30d'),
      t('confirmExtend30', 'Extend {{name}} by 30 days?', { name: user.name }),
      async () => {
        try {
          const res = await apiClient.post(`/users/${user.uuid}/extend`, { days: 30 });
          addToast(res.data?.success ? t('extendedDays', 'Extended {{name}} by 30 days', { name: user.name }) : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          fetchUsers();
        } catch { addToast(t('error'), 'error'); }
      },
      false,
      t('extend30d')
    );
  }, [addToast, fetchUsers, t]);

  const handleOpenDownloadModal = useCallback((user) => {
    setSelectedUser(user);
    setIsDownloadModalOpen(true);
  }, []);

  const handleExportCsv = useCallback(() => {
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
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    addToast(t('exported', 'CSV exported'), 'success');
  }, [filteredUsers, addToast, t]);

  const handleResetUsage = useCallback(async (user) => {
    openConfirm(
      t('resetUsage'),
      t('confirmResetUsage', 'Reset used traffic for {{name}}?', { name: user.name }),
      async () => {
        try {
          const res = await apiClient.post(`/users/${user.uuid}/reset-usage`);
          addToast(res.data?.success ? t('resetDone') : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          fetchUsers();
        } catch { addToast(t('error'), 'error'); }
      },
      false,
      t('resetUsage')
    );
  }, [addToast, fetchUsers, t]);

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div id="users-view" className="view">
      <div className="view-header">
        <h2>{t('users')}</h2>
        <div className="view-header-actions">
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleExportCsv}>
            <FiDownload size={14} aria-hidden="true" /> {t('exportCsv')}
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setIsAddModalOpen(true)}>
            <FiPlus size={14} aria-hidden="true" /> {t('addUser')}
          </button>
        </div>
      </div>

      {/* Stat cards */}
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

      {/* Search + filters */}
      <div className="search-with-filters">
        <label className="search-field" style={{ flex: 1, maxWidth: 280 }}>
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
          <button key={f.id} type="button" className={`filter-chip${view === f.id ? ' active' : ''}`} onClick={() => setView(f.id)}>
            {f.label} <span className="count">{filterCounts[f.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading && users.length === 0 ? (
        <EmptyState title={t('loading', 'Loading…')} description="" />
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
        <div className="placeholder-list">
          <p className="placeholder-notice">{t('listRemoved', 'Table removed — UI will be redesigned. Current users: {count}', { count: filteredUsers.length })}</p>
        </div>
      )}

      {/* ── Modals ── */}
      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm}
        title={confirm.title}
        message={confirm.message}
        danger={confirm.danger}
        confirmLabel={confirm.confirmLabel}
      />
      <AddUserModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onUserAdded={async () => {
          addToast(t('userCreated', 'User created'), 'success');
          setIsAddModalOpen(false);
          fetchUsers();
        }}
        subscriptionSettings={null}
      />
      <EditUserModal
        isOpen={isEditModalOpen}
        onClose={() => { setIsEditModalOpen(false); setSelectedUser(null); }}
        user={selectedUser}
        onUserUpdated={async () => {
          addToast(t('userUpdated'), 'success');
          setIsEditModalOpen(false);
          setSelectedUser(null);
          fetchUsers();
        }}
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
      />
      <UserDetailModal
        isOpen={isDetailModalOpen}
        onClose={() => { setIsDetailModalOpen(false); setSelectedUser(null); }}
        user={selectedUser}
        onEdit={handleEdit}
        onDelete={handleDelete}
        onSessions={handleShowSessions}
        onExtend={handleExtendSingle}
        onDownload={handleOpenDownloadModal}
        onResetUsage={handleResetUsage}
        onCopyLink={async (u) => { await copyText(getSubscriptionLink(u)); addToast(t('linkCopied'), 'success'); }}
        onShowQR={handleUserClick}
        subscriptionLink={(u) => getSubscriptionLink(u)}
      />
    </div>
  );
};

export default UserManagement;