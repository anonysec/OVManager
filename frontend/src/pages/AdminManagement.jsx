import { useEffect, useMemo, useState, useCallback } from 'react';
import { FiUserCheck, FiSearch, FiPlus } from 'react-icons/fi';
import apiClient from '../services/api';
import AddAdminModal from '../components/AddAdminModal';
import EditAdminModal from '../components/EditAdminModal';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import ConfirmModal from '../components/ConfirmModal';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';

const AdminManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [admins, setAdmins] = useState([]);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const openConfirm = (title, message, onConfirm) => setConfirm({ open: true, title, message, onConfirm });
  const closeConfirm = () => setConfirm(c => ({ ...c, open: false }));
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedAdmin, setSelectedAdmin] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  const fetchAdmins = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const response = await apiClient.get('/admin/');
      if (response.data.success) {
        setAdmins(response.data.data || []);
      }
    } catch (error) {
      console.error('Error fetching admins:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { fetchAdmins(); }, [fetchAdmins]);

  const adminStats = useMemo(() => ({
    total: admins.length,
    active: admins.filter(a => a.is_active !== false).length,
  }), [admins]);

  const filteredAdmins = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return admins.filter(a => !term || (a.username || '').toLowerCase().includes(term));
  }, [admins, searchTerm]);

  const handleDelete = (admin) => {
    openConfirm(
      t('deleteAdmin'),
      t('confirmDeleteAdmin', 'Delete admin {{name}}? This cannot be undone.', { name: admin.username }),
      async () => {
        try {
          const res = await apiClient.delete(`/admin/${admin.id}`);
          addToast(res.data?.success ? t('deleted') : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          fetchAdmins();
        } catch { addToast(t('error'), 'error'); }
      }
    );
  };
  // Expose for future quick-actions menu (currently only available through
  // the Add/Edit modal flow, but the row-level handler stays in place).
  void handleDelete;

  const handleEdit = (admin) => {
    setSelectedAdmin(admin);
    setIsEditModalOpen(true);
  };
  void handleEdit;

  return (
    <div id="admins-view" className="view">
      <div className="view-header">
        <h2>{t('admins')}</h2>
        <div className="view-header-actions">
          <button type="button" onClick={() => setIsAddModalOpen(true)} className="btn">
            <FiPlus aria-hidden="true" />
            <span>{t('addNewAdmin', 'Add admin')}</span>
          </button>
        </div>
      </div>

      <div className="user-stats-row">
        <div className="user-stat" style={{ '--us-accent': '#ff7a1e' }}>
          <span className="us-ico"><FiUserCheck /></span>
          <span className="us-body">
            <span className="us-label">{t('adminsTotal', 'Total admins')}</span>
            <span className="us-value">{adminStats.total}</span>
          </span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#43a047' }}>
          <span className="us-ico"><FiUserCheck /></span>
          <span className="us-body">
            <span className="us-label">{t('adminsActive', 'Active')}</span>
            <span className="us-value">{adminStats.active}</span>
          </span>
        </div>
      </div>

      <div className="search-pagination-controls">
        <label className="search-field" style={{ flex: 1, maxWidth: 280 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input
            type="search"
            placeholder={t('searchAdminPlaceholder', 'Search by username…')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="search-input"
            aria-label={t('searchAdminPlaceholder', 'Search by username…')}
          />
        </label>
        <div className="results-meta" aria-live="polite">
          <strong>{filteredAdmins.length}</strong> {t('results', 'results')}
          {searchTerm && (
            <button type="button" className="toolbar-clear" onClick={() => setSearchTerm('')}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

      {loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={fetchAdmins} retryLabel={t('retry')} />
      ) : !isLoading && admins.length === 0 ? (
        <EmptyState
          title={t('noAdminsTitle', 'No admins configured')}
          description={t('noAdminsBody', 'Add an admin to get started.')}
          actionLabel={t('addNewAdmin', 'Add admin')}
          onAction={() => setIsAddModalOpen(true)}
        />
      ) : (
        <div className="placeholder-list">
          <p className="placeholder-notice">{t('listRemoved', 'Table removed — UI will be redesigned. Current admins: {count}', { count: filteredAdmins.length })}</p>
        </div>
      )}

      <AddAdminModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onAdminCreated={async () => {
          addToast(t('adminCreated', 'Admin created'), 'success');
          setIsAddModalOpen(false);
          fetchAdmins();
        }}
      />
      <EditAdminModal
        isOpen={isEditModalOpen}
        onClose={() => { setIsEditModalOpen(false); setSelectedAdmin(null); }}
        admin={selectedAdmin}
        onAdminUpdated={async () => {
          addToast(t('adminUpdated', 'Admin updated'), 'success');
          setIsEditModalOpen(false);
          setSelectedAdmin(null);
          fetchAdmins();
        }}
      />
      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm}
        title={confirm.title}
        message={confirm.message}
      />
    </div>
  );
};

export default AdminManagement;