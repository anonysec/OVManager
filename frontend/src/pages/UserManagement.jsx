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
import { FiSearch } from 'react-icons/fi';
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
  const [view, setView] = useState('all'); // 'all' | 'online' | 'inactive' | 'expiring'
  const [selected, setSelected] = useState([]);
  const [sort, setSort] = useState({ key: 'name', dir: 'asc' });
  const [bulkBusy, setBulkBusy] = useState(false);

  const fetchUsers = async () => {
    try {
      const response = await apiClient.get('/users/');
      if (response.data.success && Array.isArray(response.data.data)) {
        setUsers(response.data.data.slice().reverse());
      } else {
        setUsers([]);
      }
    } catch (error) {
      console.error("Error fetching users:", error);
      setUsers([]);
    }
  };

  const fetchSubscriptionSettings = async () => {
    try {
      const response = await apiClient.get('/server/settings');
      if (response.data.success && response.data.data) {
        setSubscriptionSettings(response.data.data);
      }
    } catch (error) {
      console.error("Error fetching subscription settings:", error);
    }
  };

  useEffect(() => {
    fetchUsers();
    fetchSubscriptionSettings();
  }, []);

  // Deep-link: ?user=<uuid> opens that user's edit modal
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

  const userStats = useMemo(() => {
    const activeUsersCount = users.filter(user => user.is_active).length;
    const onlineUsersCount = users.filter(user => user.online || Number(user.active_connections || 0) > 0).length;
    const inactiveUsersCount = users.length - activeUsersCount;
    return {
      total: users.length,
      active: activeUsersCount,
      inactive: inactiveUsersCount,
      online: onlineUsersCount,
    };
  }, [users]);

  // Filter + sort Data
  const filteredUsers = useMemo(() => {
    const term = searchTerm.toLowerCase();
    let list = users.filter((user) => {
      if (!user.name.toLowerCase().includes(term)) return false;
      if (view === 'online') return user.online || Number(user.active_connections || 0) > 0;
      if (view === 'inactive') return !user.is_active;
      if (view === 'expiring') return daysUntil(user.expiry_date) >= 0 && daysUntil(user.expiry_date) <= 7;
      return true; // 'all'
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
        av = Number(a.total ?? 0);
        bv = Number(b.total ?? 0);
      } else if (key === 'max_logins') {
        av = Number(a.max_logins ?? 0);
        bv = Number(b.max_logins ?? 0);
      } else {
        av = a[key];
        bv = b[key];
      }
      if (av < bv) return -1 * mul;
      if (av > bv) return 1 * mul;
      return 0;
    });
    return list;
  }, [users, searchTerm, view, sort]);

  const handleSort = (key) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));
  };

  const handleSelect = (uuid) => {
    setSelected((s) => (s.includes(uuid) ? s.filter((x) => x !== uuid) : [...s, uuid]));
  };
  const handleSelectAll = (checked) => {
    if (checked) setSelected(filteredUsers.map((u) => u.uuid));
    else setSelected([]);
  };

  const handleDelete = async (user) => {
    if (!window.confirm(`Are you sure you want to delete user ${user.name}?`)) return;
    try {
      await apiClient.delete(`/users/${user.uuid}`);
      addToast(`User ${user.name} deleted successfully.`, 'success');
      setSelected((s) => s.filter((x) => x !== user.uuid));
      fetchUsers();
    } catch {
      addToast('Error deleting user.', 'error');
    }
  };

  const handleBulkDelete = async (uuids) => {
    if (!window.confirm(`Delete ${uuids.length} selected user(s)? This cannot be undone.`)) return;
    setBulkBusy(true);
    try {
      await Promise.all(uuids.map((uuid) => apiClient.delete(`/users/${uuid}`).catch(() => null)));
      setSelected([]);
      fetchUsers();
    } finally {
      setBulkBusy(false);
    }
  };

  const handleToggleStatus = async (user) => {
    const newStatus = !user.is_active;
    const statusLabel = newStatus ? 'activate' : 'deactivate';
    if (!window.confirm(`Are you sure you want to ${statusLabel} user ${user.name}?`)) return;
    try {
      const response = await apiClient.put(`/users/${user.uuid}/status`, {
        name: user.name,
        status: !user.is_active
      });
      if (response.data.success) {
        addToast(`User ${user.name} ${statusLabel}d successfully.`, 'success');
        fetchUsers();
      } else {
        addToast(`Failed to ${statusLabel} user.`, 'error');
      }
    } catch {
      addToast(`Error ${statusLabel}ing user.`, 'error');
    }
  };

  const handleResetUsage = async (user) => {
    if (!window.confirm(`Are you sure you want to reset usage for user ${user.name}?`)) return;

    try {
      const response = await apiClient.get(`/users/${user.uuid}`);
      if (response.data.success) {
        addToast(`Usage for ${user.name} has been reset.`, 'Success');
        fetchUsers();
      } else {
        addToast(`Failed to reset usage for ${user.name}.`, 'Error');
      }
    } catch {
      addToast('Error resetting usage.', 'Error');
    }
  };

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
      if (Array.isArray(detail)) {
        setSessionError(detail.map(d => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setSessionError(JSON.stringify(detail));
      } else {
        setSessionError(detail || 'Failed to load session diagnostics.');
      }
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

  const handleDisconnectUser = async () => {
    if (!selectedUser?.uuid) return;
    if (!window.confirm(`Disconnect active/stale sessions for ${selectedUser.name}?`)) return;
    setSessionLoading(true);
    setSessionError('');
    try {
      const response = await apiClient.post(`/users/${selectedUser.uuid}/disconnect`);
      if (!response.data.success) {
        setSessionError(response.data.msg || 'Disconnect failed.');
      }
      await fetchSessionDiagnostics(selectedUser);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setSessionError(detail.map(d => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setSessionError(JSON.stringify(detail));
      } else {
        setSessionError(detail || 'Disconnect failed.');
      }
    } finally {
      setSessionLoading(false);
    }
  };

  const handleOpenDownloadModal = (user) => {
    setSelectedUser(user);
    setIsDownloadModalOpen(true);
  };

  const handleUserAdded = () => {
    setIsAddModalOpen(false);
    addToast('User created successfully.', 'success');
    fetchUsers();
  };

  const handleUserClick = (user) => {
    setSelectedUser(user);
    setIsDetailModalOpen(true);
  };

  const handleEdit = (user) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  };

  const handleUserUpdated = () => {
    setIsEditModalOpen(false);
    setSelectedUser(null);
    addToast('User updated successfully.', 'success');
    fetchUsers();
  };

  // Generate subscription link for each user. Fall back to the panel's own
  // origin + base path when no subscription prefix is configured, so a usable
  // per-user link always exists.
  const getSubscriptionLink = (user) => {
    if (!user || !user.uuid) return '';
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
          <button onClick={() => setIsAddModalOpen(true)} className="btn">{t('addNewUser')}</button>
        </div>
      </div>

      <div className="user-stats-row">
        <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
          <span className="us-ico"><BsPersonFill /></span>
          <span className="us-body">
            <span className="us-label">{t('totalUsers')}</span>
            <span className="us-value">{userStats.total}</span>
          </span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#43a047' }}>
          <span className="us-ico"><BsPersonCheckFill /></span>
          <span className="us-body">
            <span className="us-label">{t('activeUsers')}</span>
            <span className="us-value">{userStats.active}</span>
          </span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#66bb6a' }}>
          <span className="us-ico"><BsPersonPlusFill /></span>
          <span className="us-body">
            <span className="us-label">{t('onlineUsers')}</span>
            <span className="us-value">{userStats.online}</span>
          </span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#e53935' }}>
          <span className="us-ico"><BsPersonXFill /></span>
          <span className="us-body">
            <span className="us-label">{t('inactiveUsers')}</span>
            <span className="us-value">{userStats.inactive}</span>
          </span>
        </div>
      </div>

      <div className="search-with-filters">
        <label className="search-field" style={{ flex: 1, maxWidth: 380 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input type="search" placeholder="Search by username..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="search-input" aria-label="Search users by username" />
        </label>
        <div className="seg-toggle" role="tablist" aria-label="User view">
          <button type="button" role="tab" aria-selected={view === 'all'} className={`seg-tab${view === 'all' ? ' active' : ''}`} onClick={() => setView('all')}>{t('tabAll')}</button>
          <button type="button" role="tab" aria-selected={view === 'online'} className={`seg-tab${view === 'online' ? ' active' : ''}`} onClick={() => setView('online')}>{t('tabOnline')}</button>
          <button type="button" role="tab" aria-selected={view === 'inactive'} className={`seg-tab${view === 'inactive' ? ' active' : ''}`} onClick={() => setView('inactive')}>{t('tabInactive')}</button>
          <button type="button" role="tab" aria-selected={view === 'expiring'} className={`seg-tab${view === 'expiring' ? ' active' : ''}`} onClick={() => setView('expiring')}>{t('tabExpiring')}</button>
        </div>
      </div>

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
        onShowSessions={handleShowSessions}
        getSubscriptionLink={getSubscriptionLink}
      />
      {isDetailModalOpen && (
        <UserDetailModal
          isOpen={isDetailModalOpen}
          user={selectedUser}
          subscriptionLink={selectedUser ? getSubscriptionLink(selectedUser) : ''}
          onClose={() => setIsDetailModalOpen(false)}
          onEdit={handleEdit}
          onSessions={handleShowSessions}
          onDownload={handleOpenDownloadModal}
          onCopyId={(u) => copyText(u.uuid || '')}
          onToggleStatus={handleToggleStatus}
        />
      )}
      {isAddModalOpen && (
        <AddUserModal
          isOpen={isAddModalOpen}
          onClose={() => setIsAddModalOpen(false)}
          onUserAdded={handleUserAdded}
        />
      )}
      {isEditModalOpen && (
        <EditUserModal
          isOpen={isEditModalOpen}
          user={selectedUser}
          onClose={() => setIsEditModalOpen(false)}
          onUserUpdated={handleUserUpdated}
        />
      )}
      {isDownloadModalOpen && (
        <SelectNodeForDownloadModal
          isOpen={isDownloadModalOpen}
          user={selectedUser}
          onClose={() => setIsDownloadModalOpen(false)}
        />
      )}
      {isSessionsModalOpen && (
        <UserSessionsModal
          isOpen={isSessionsModalOpen}
          user={selectedUser}
          data={sessionDiagnostics}
          loading={sessionLoading}
          error={sessionError}
          onClose={() => setIsSessionsModalOpen(false)}
          onRefresh={() => fetchSessionDiagnostics(selectedUser)}
          onDisconnect={handleDisconnectUser}
        />
      )}
    </div>
  );
};

export default UserManagement;