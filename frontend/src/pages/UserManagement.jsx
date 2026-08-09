import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import apiClient from '../services/api';
import { useToast } from '../context/ToastContext';
import UserTable from '../components/UserTable';
import AddUserModal from '../components/AddUserModal';
import EditUserModal from '../components/EditUserModal';
import SelectNodeForDownloadModal from '../components/SelectNodeForDownloadModal';
import UserSessionsModal from '../components/UserSessionsModal';
import UserDetailModal from '../components/UserDetailModal';
import ConfirmModal from '../components/ConfirmModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
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

  // ── ConfirmModal state ────────────────────────────────────────────────
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null, danger: true });

  const openConfirm = (title, message, onConfirm, danger = true) =>
    setConfirm({ open: true, title, message, onConfirm, danger });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  // ── Data fetching ─────────────────────────────────────────────────────
  const fetchUsers = async () => {
    setLoadError(false);
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

  useEffect(() => {
    fetchUsers();
    fetchSubscriptionSettings();
  }, []);

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

  // ── Filter + sort ─────────────────────────────────────────────────────
  const filteredUsers = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    let list = users.filter((user) => {
      if (!String(user.name || '').toLowerCase().includes(term)) return false;
      if (view === 'online') return user.online || Number(user.active_connections || 0) > 0;
      if (view === 'inactive') return !user.is_active;
      if (view === 'expiring') return daysUntil(user.expiry_date) >= 0 && daysUntil(user.expiry_date) <= 7;
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
  }, [users, searchTerm, view, sort]);

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
          fetchUsers();
        } catch {
          addToast(t('userDeleteError', { name: user.name }, `Failed to delete "${user.name}".`), 'error');
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
  const handleEdit = (user) => { setSelectedUser(user); setIsEditModalOpen(true); };
  const handleUserUpdated = () => { setIsEditModalOpen(false); setSelectedUser(null); addToast('User updated successfully.', 'success'); fetchUsers(); };

  const getSubscriptionLink = (user) => {
    if (!user?.uuid) return '';
    const urlpath = (import.meta.env.VITE_URLPATH || '').replace(/^\/+|\/+$/g, '');
    const base = urlpath ? `${window.location.origin}/${urlpath}` : window.location.origin;
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
        <div className="seg-toggle" role="tablist" aria-label="User view">
          {['all', 'online', 'inactive', 'expiring'].map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} className={`seg-tab${view === v ? ' active' : ''}`} onClick={() => setView(v)}>
              {t(`tab${v.charAt(0).toUpperCase() + v.slice(1)}`, v)}
            </button>
          ))}
        </div>
        <div className="results-meta" aria-live="polite">
          <strong>{filteredUsers.length}</strong> {t('results', 'results')}
          {(searchTerm || view !== 'all') && (
            <button type="button" className="toolbar-clear" onClick={() => { setSearchTerm(''); setView('all'); }}>{t('clear', 'Clear')}</button>
          )}
        </div>
      </div>

      {loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={fetchUsers} retryLabel={t('retry')} />
      ) : users.length === 0 ? (
        <EmptyState title={t('noUsersTitle')} description={t('noUsersBody')} actionLabel={t('addNewUser')} onAction={() => setIsAddModalOpen(true)} />
      ) : (
        <UserTable
          users={filteredUsers}
          isLoading={false}
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
    </div>
  );
};

export default UserManagement;
