import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import apiClient from '../services/api';
import UserTable from '../components/UserTable';
import AddUserModal from '../components/AddUserModal';
import EditUserModal from '../components/EditUserModal';
import SelectNodeForDownloadModal from '../components/SelectNodeForDownloadModal';
import UserSessionsModal from '../components/UserSessionsModal';
import UserStatCard from '../components/UserStatCard';
import { FiSearch } from 'react-icons/fi';
import { BsPersonFill, BsPersonCheckFill, BsPersonXFill } from 'react-icons/bs';
import { useTranslation } from 'react-i18next';
import { daysUntil } from '../utils/time';

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
  const [selectedUser, setSelectedUser] = useState(null);
  const { t } = useTranslation();


  const [searchTerm, setSearchTerm] = useState('');
  const [view, setView] = useState('all'); // 'all' | 'online' | 'inactive' | 'expiring'

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
  }, [users]);

  const userStats = useMemo(() => {
    const activeUsersCount = users.filter(user => user.is_active).length;
    const inactiveUsersCount = users.length - activeUsersCount;
    return {
      total: users.length,
      active: activeUsersCount,
      inactive: inactiveUsersCount,
    };
  }, [users]);

  // Filter Data
  const filteredUsers = useMemo(() => {
    const term = searchTerm.toLowerCase();
    return users.filter((user) => {
      if (!user.name.toLowerCase().includes(term)) return false;
      if (view === 'online') return user.online;
      if (view === 'inactive') return !user.is_active;
      if (view === 'expiring') return daysUntil(user.expiry_date) >= 0 && daysUntil(user.expiry_date) <= 7;
      return true; // 'all'
    });
  }, [users, searchTerm, view]);

  const handleSearchChange = (event) => {
    setSearchTerm(event.target.value);
  };

  const handleDelete = async (uuid, name) => {
    if (!window.confirm(`Are you sure you want to delete user ${name}?`)) return;
    try {
      await apiClient.delete(`/users/${uuid}`);
      console.warn(`User ${name} deleted successfully.`);
      fetchUsers();
    } catch {
      console.warn('Error deleting user.');
    }
  };

  const handleToggleStatus = async (user) => {
    const newStatus = !user.is_active;
    const statusLabel = newStatus ? 'activate' : 'deactivate';
    if (!window.confirm(`Are you sure you want to ${statusLabel} user ${user.name}?`)) return;

    try {
      const response = await apiClient.put(`/users/${user.uuid}/status`, {
        name: user.name,
        status: !user.is_active,
        expiry_date: null
      });
      if (response.data.success) {
        console.warn(`User ${statusLabel}d successfully.`);
        fetchUsers();
      } else {
        console.warn(`Failed to ${statusLabel} user.`);
      }
    } catch {
      console.warn(`Error ${statusLabel}ing user.`);
    }
  };

  const handleResetUsage = async (user) => {
    if (!window.confirm(`Are you sure you want to reset usage for user ${user.name}?`)) return;

    try {
      const response = await apiClient.get(`/users/${user.uuid}`);
      if (response.data.success) {
        console.warn(`Usage for ${user.name} has been reset.`);
        fetchUsers();
      } else {
        console.warn(`Failed to reset usage for ${user.name}.`);
      }
    } catch {
      console.warn('Error resetting usage.');
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
      setSessionError(err.response?.data?.detail || 'Failed to load session diagnostics.');
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
      setSessionError(err.response?.data?.detail || 'Disconnect failed.');
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
    fetchUsers();
  };

  const handleEdit = (user) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  };

  const handleUserUpdated = () => {
    setIsEditModalOpen(false);
    setSelectedUser(null);
    fetchUsers();
  };

  // Generate subscription link for each user
  const getSubscriptionLink = (user) => {
    if (!subscriptionSettings || !user || !user.uuid) return '';
    let prefix = subscriptionSettings.subscription_url_prefix;
    let path = subscriptionSettings.subscription_path || '';
    if (!prefix.endsWith('/')) prefix += '/';
    if (path.startsWith('/')) path = path.slice(1);
    if (path && !path.endsWith('/')) path += '/';
    return `${prefix}${path}${user.uuid}`;
  };

  return (
    <div id="users-view" className="view">
      <div className="view-header">
        <h2>Users</h2>
        <div className="view-header-actions">
          <div className="seg-toggle" role="tablist" aria-label="User view">
            <button type="button" role="tab" aria-selected={view === 'all'} className={view === 'all' ? 'active' : ''} onClick={() => setView('all')}>All</button>
            <button type="button" role="tab" aria-selected={view === 'online'} className={view === 'online' ? 'active' : ''} onClick={() => setView('online')}>Online</button>
            <button type="button" role="tab" aria-selected={view === 'inactive'} className={view === 'inactive' ? 'active' : ''} onClick={() => setView('inactive')}>Inactive</button>
            <button type="button" role="tab" aria-selected={view === 'expiring'} className={view === 'expiring' ? 'active' : ''} onClick={() => setView('expiring')}>Expiring ≤7d</button>
          </div>
          <button onClick={() => setIsAddModalOpen(true)} className="btn">{t('addNewUser')}</button>
        </div>
      </div>

      <div className="stats-grid" style={{ marginBottom: '30px', display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
        <UserStatCard
          icon={<BsPersonFill style={{ fontSize: 28 }} />}
          label={t('totalUsers')}
          value={userStats.total}
          color="#90caf9"
          className="card-dark"
        />
        <UserStatCard
          icon={<BsPersonCheckFill style={{ fontSize: 28 }} />}
          label={t('activeUsers')}
          value={userStats.active}
          color="#43a047"
          className="card-dark"
        />
        <UserStatCard
          icon={<BsPersonXFill style={{ fontSize: 28 }} />}
          label={t('inactiveUsers')}
          value={userStats.inactive}
          color="#e53935"
          className="card-dark"
        />
      </div>

      <div className="search-pagination-controls">
        <label className="search-field">
          <FiSearch className="search-icon" aria-hidden="true" />
          <input
            type="search"
            placeholder="Search by username..."
            value={searchTerm}
            onChange={handleSearchChange}
            className="search-input"
            aria-label="Search users by username"
          />
        </label>
      </div>

      <UserTable
        users={filteredUsers}
        onDelete={handleDelete}
        onDownload={handleOpenDownloadModal}
        onEdit={handleEdit}
        onToggleStatus={handleToggleStatus}
        onResetUsage={handleResetUsage}
        onShowSessions={handleShowSessions}
        getSubscriptionLink={getSubscriptionLink}
      />
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