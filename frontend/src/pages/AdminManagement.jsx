import { useEffect, useMemo, useState, useCallback } from 'react';
import { FiUserCheck, FiSearch, FiPlus, FiEdit2, FiTrash2 } from 'react-icons/fi';
import apiClient from '../services/api';
import AddAdminModal from '../components/AddAdminModal';
import EditAdminModal from '../components/EditAdminModal';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import ConfirmModal from '../components/ConfirmModal';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import DataTable from '../components/ui/DataTable';
import StatusBadge from '../components/ui/StatusBadge';

const PAGE_SIZE_KEY = 'ovmanager-ui-admins-pagesize';

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
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [sort, setSort] = useState({ key: 'username', dir: 'asc' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const currentUsername = localStorage.getItem('username') || '';

  const fetchAdmins = useCallback(async ({ background = false } = {}) => {
    if (!background) setIsLoading(true);
    setLoadError(false);
    try {
      const response = await apiClient.get('/admin/');
      if (response.data.success) {
        setAdmins(response.data.data || []);
      } else {
        setLoadError(true);
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
    totalUsers: admins.reduce((s, a) => s + Number(a.users_count || 0), 0),
  }), [admins]);

  const filteredAdmins = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    if (!term) return admins;
    return admins.filter((a) => {
      const hay = `${a.username || ''} ${a.username_prefix || ''} ${a.telegram_id ?? ''}`.toLowerCase();
      return hay.includes(term);
    });
  }, [admins, searchTerm]);

  const sortedAdmins = useMemo(() => {
    const arr = [...filteredAdmins];
    const mul = sort.dir === 'desc' ? -1 : 1;
    const val = (a) => {
      switch (sort.key) {
        case 'username': return (a.username || '').toLowerCase();
        case 'users_count': return Number(a.users_count || 0);
        case 'username_prefix': return (a.username_prefix || '').toLowerCase();
        default: return a[sort.key];
      }
    };
    arr.sort((a, b) => {
      const va = val(a); const vb = val(b);
      if (va < vb) return -1 * mul;
      if (va > vb) return 1 * mul;
      return 0;
    });
    return arr;
  }, [filteredAdmins, sort]);

  const pagedAdmins = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sortedAdmins.slice(start, start + pageSize);
  }, [sortedAdmins, page, pageSize]);

  const onSort = useCallback((key) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));
  }, []);

  const handleDelete = (admin) => {
    if (admin.username === currentUsername) {
      addToast(t('cannotDeleteSelf', 'You cannot delete your own admin account.'), 'warning');
      return;
    }
    openConfirm(
      t('deleteAdmin'),
      t('confirmDeleteAdmin', 'Delete admin "{{name}}"? Their users will remain but become unassigned.', { name: admin.username }),
      async () => {
        try {
          // Backend contract: DELETE /admin/{username} (not id).
          const res = await apiClient.delete(`/admin/${encodeURIComponent(admin.username)}`);
          addToast(res.data?.success ? t('deleted') : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          setSelected((prev) => { const n = new Set(prev); n.delete(String(admin.username)); return n; });
          fetchAdmins({ background: true });
        } catch { addToast(t('error'), 'error'); }
      }
    );
  };

  const handleEdit = (admin) => {
    setSelectedAdmin(admin);
    setIsEditModalOpen(true);
  };

  const runBulkDelete = async () => {
    const names = [...selected].filter((n) => n !== currentUsername);
    if (names.length === 0) {
      addToast(t('cannotDeleteSelf', 'You cannot delete your own admin account.'), 'warning');
      return;
    }
    setBulkBusy(true);
    let ok = 0; let fail = 0;
    for (const username of names) {
      try {
        const res = await apiClient.delete(`/admin/${encodeURIComponent(username)}`);
        if (res.data?.success) ok += 1; else fail += 1;
      } catch { fail += 1; }
    }
    setBulkBusy(false);
    setSelected(new Set());
    fetchAdmins({ background: true });
    addToast(fail === 0 ? t('bulkDeleteDone', 'Deleted {{ok}} admins.', { ok }) : t('bulkPartial', '{{ok}} done, {{fail}} failed.', { ok, fail }), fail === 0 ? 'success' : 'warning');
  };

  const columns = useMemo(() => [
    {
      key: 'username', label: t('th_admin', 'Admin'), sortable: true,
      render: (a) => (
        <span className="dt-cell-main">
          <span className="dt-avatar" aria-hidden="true">{String(a.username || '?').slice(0, 1).toUpperCase()}</span>
          <span style={{ minWidth: 0 }}>
            <span className="dt-cell-title">{a.username}{a.username === currentUsername ? ` (${t('you', 'you')})` : ''}</span>
            <br />
            <span className="dt-cell-sub">{a.username_prefix ? `${t('usernamePrefix', 'Prefix')}: ${a.username_prefix}` : t('noPrefix', 'No prefix')}</span>
          </span>
        </span>
      ),
    },
    {
      key: 'users_count', label: t('th_users_col', 'Users'), sortable: true, className: 'dt-num',
      render: (a) => Number(a.users_count || 0),
    },
    {
      key: 'telegram_id', label: t('telegramId', 'Telegram ID'), hideOnMobile: true,
      render: (a) => (a.telegram_id ?? '—'),
    },
    {
      key: 'status', label: t('th_status', 'Status'),
      render: (a) => (
        <StatusBadge
          status={a.is_active === false ? 'offline' : 'online'}
          label={a.is_active === false ? t('inactive', 'Inactive') : t('active', 'Active')}
        />
      ),
    },
    {
      key: 'actions', label: t('th_actions', 'Actions'),
      render: (a) => {
        const isSelf = a.username === currentUsername;
        return (
          <span className="dt-actions" role="group" aria-label={`${a.username} ${t('actions', 'Actions')}`}>
            <button type="button" className="dt-icon-btn" title={t('editButton', 'Edit')} aria-label={`${t('editButton', 'Edit')} ${a.username}`} onClick={() => handleEdit(a)}><FiEdit2 size={15} /></button>
            <button
              type="button" className="dt-icon-btn is-danger" title={isSelf ? t('cannotDeleteSelf', 'You cannot delete your own admin account.') : t('deleteButton', 'Delete')}
              aria-label={`${t('deleteButton', 'Delete')} ${a.username}`} aria-disabled={isSelf}
              disabled={isSelf} style={isSelf ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
              onClick={() => handleDelete(a)}
            >
              <FiTrash2 size={15} />
            </button>
          </span>
        );
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t, currentUsername]);

  const allPageKeys = pagedAdmins.map((a) => String(a.username));
  const allSelected = allPageKeys.length > 0 && allPageKeys.every((k) => selected.has(k));
  const someSelected = allPageKeys.some((k) => selected.has(k));

  return (
    <div id="admins-view" className="view">
      <div className="view-header">
        <h2>{t('admins')}</h2>
        <div className="view-header-actions">
          <button type="button" onClick={() => setIsAddModalOpen(true)} className="btn btn-primary btn-sm">
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
        <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
          <span className="us-ico"><FiUserCheck /></span>
          <span className="us-body">
            <span className="us-label">{t('th_users_col', 'Users')}</span>
            <span className="us-value">{adminStats.totalUsers}</span>
          </span>
        </div>
      </div>

      <div className="search-pagination-controls">
        <label className="search-field" style={{ flex: 1, maxWidth: 320 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input
            type="search"
            placeholder={t('searchAdminPlaceholder', 'Search by username…')}
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setPage(1); }}
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

      {selected.size > 0 && (
        <div className="dt-bulkbar" role="toolbar" aria-label={t('bulkActions', 'Bulk actions')}>
          <strong>{t('selectedCount', '{{count}} selected', { count: selected.size })}</strong>
          <button
            type="button" className="btn btn-danger btn-sm" disabled={bulkBusy}
            onClick={() => openConfirm(t('deleteButton', 'Delete'), t('confirmBulkDelete', 'Delete {{count}} selected admins?', { count: selected.size }), runBulkDelete)}
          >
            <FiTrash2 size={13} /> {t('delete', 'Delete')}
          </button>
          <button type="button" className="toolbar-clear" onClick={() => setSelected(new Set())}>{t('clear', 'Clear')}</button>
        </div>
      )}

      {isLoading ? (
        <DataTable columns={columns} rows={[]} loading density="comfort" />
      ) : loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchAdmins()} retryLabel={t('retry')} />
      ) : admins.length === 0 ? (
        <EmptyState
          title={t('noAdminsTitle', 'No admins configured')}
          description={t('noAdminsBody', 'Add an admin to get started.')}
          actionLabel={t('addNewAdmin', 'Add admin')}
          onAction={() => setIsAddModalOpen(true)}
        />
      ) : filteredAdmins.length === 0 ? (
        <EmptyState
          title={t('noMatchesTitle', 'No matching admins')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={() => setSearchTerm('')}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={pagedAdmins}
          rowKey={(r) => String(r.username)}
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
          total={sortedAdmins.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); localStorage.setItem(PAGE_SIZE_KEY, String(n)); setPage(1); }}
          caption={t('admins', 'Admins')}
        />
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
