import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  FiUserCheck, FiSearch, FiPlus, FiEdit2, FiTrash2, FiUsers,
  FiMonitor, FiPower, FiRefreshCw,
} from 'react-icons/fi';
import apiClient from '../services/api';
import AdminFormModal from '../components/AdminFormModal';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import ConfirmModal from '../components/ConfirmModal';
import Modal from '../components/Modal';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import DataTable from '../components/ui/DataTable';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import StatCard from '../components/ui/StatCard';
import { fmtDateTime, fmtRelative } from '../utils/time';
import './AdminManagement.css';

const PAGE_SIZE_KEY = 'ovmanager-ui-admins-pagesize';

/** Epoch seconds -> ISO string (the API returns numeric timestamps). */
const toIso = (value) => {
  const n = Number(value);
  if (!n) return '';
  return new Date(n * 1000).toISOString();
};

/**
 * Sessions modal — active bearer sessions for one admin, with a
 * "Sign out all devices" action. Fetches on open via the owner-only
 * /admin/{username}/sessions endpoints.
 */
const AdminSessionsModal = ({ admin, onClose }) => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const username = admin?.username || '';
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = useCallback(async () => {
    if (!username) return;
    setLoading(true);
    setError(false);
    try {
      const res = await apiClient.get(`/admin/${encodeURIComponent(username)}/sessions`);
      if (res.data?.success) setSessions(res.data.data || []);
      else {
        setError(true);
        addToast(res.data?.msg || t('error'), 'error');
      }
    } catch (e) {
      setError(true);
      addToast(e.response?.data?.detail || e.response?.data?.msg || t('error'), 'error');
    } finally {
      setLoading(false);
    }
  }, [username, t, addToast]);

  useEffect(() => { if (admin) load(); }, [admin, load]);

  const revokeAll = async () => {
    setRevoking(true);
    try {
      const res = await apiClient.post(`/admin/${encodeURIComponent(username)}/sessions/revoke`);
      if (res.data?.success) {
        addToast(res.data.msg || t('adminsSessionsRevoked', 'Signed out all devices.'), 'success');
        setSessions([]);
      } else {
        addToast(res.data?.msg || t('error'), 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || e.response?.data?.msg || t('error'), 'error');
    } finally {
      setRevoking(false);
    }
  };

  return (
    <Modal
      isOpen={!!admin}
      onClose={onClose}
      title={`${t('adminsSessionsTitle', 'Active sessions')} — ${username}`}
      size="large"
    >
      <p className="adm-modal-hint">
        {t('adminsSessionsHint', 'Devices currently signed in as this admin. Signing out revokes every session immediately.')}
      </p>

      {loading ? (
        <p className="adm-modal-state" role="status">{t('loading', 'Loading…')}</p>
      ) : error ? (
        <div className="adm-modal-error">
          <p>{t('adminsSessionsLoadError', 'Could not load sessions.')}</p>
          <Button variant="secondary" size="sm" icon={<FiRefreshCw size={13} aria-hidden="true" />} onClick={load}>
            {t('retry', 'Retry')}
          </Button>
        </div>
      ) : sessions.length === 0 ? (
        <p className="adm-modal-state">{t('adminsNoSessions', 'No active sessions.')}</p>
      ) : (
        <ul className="adm-sessions">
          {sessions.map((s) => (
            <li key={s.id} className="adm-session">
              <span className="adm-session-icon" aria-hidden="true"><FiMonitor size={16} /></span>
              <div className="adm-session-body">
                <span className="adm-session-agent">
                  {s.user_agent || t('adminsUnknownDevice', 'Unknown device')}
                </span>
                <span className="adm-session-ip">{s.ip || '—'}</span>
                <div className="adm-session-times">
                  <span>
                    <em>{t('adminsSessionCreated', 'Signed in')}</em>
                    <time dateTime={toIso(s.created_at)} title={fmtDateTime(toIso(s.created_at))}>
                      {fmtRelative(toIso(s.created_at))}
                    </time>
                  </span>
                  <span>
                    <em>{t('adminsSessionLastSeen', 'Last seen')}</em>
                    <time dateTime={toIso(s.last_seen_at)} title={fmtDateTime(toIso(s.last_seen_at))}>
                      {fmtRelative(toIso(s.last_seen_at))}
                    </time>
                  </span>
                  <span>
                    <em>{t('adminsSessionExpires', 'Expires')}</em>
                    <time dateTime={toIso(s.expires_at)} title={fmtDateTime(toIso(s.expires_at))}>
                      {fmtRelative(toIso(s.expires_at))}
                    </time>
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="modal-footer">
        <Button
          variant="ghost"
          size="sm"
          icon={<FiRefreshCw size={13} aria-hidden="true" />}
          loading={loading}
          onClick={load}
        >
          {t('refresh', 'Refresh')}
        </Button>
        <Button variant="secondary" onClick={onClose}>{t('close', 'Close')}</Button>
        <Button
          variant="danger"
          icon={<FiPower size={14} aria-hidden="true" />}
          loading={revoking}
          disabled={loading || sessions.length === 0}
          onClick={() => setConfirmOpen(true)}
        >
          {t('adminsSignOutAll', 'Sign out all devices')}
        </Button>
      </div>

      <ConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={revokeAll}
        title={t('adminsSignOutAll', 'Sign out all devices')}
        message={t('adminsConfirmSignOut', 'Sign out every device for "{{name}}"? They will need to log in again.', { name: username })}
        confirmLabel={t('adminsSignOutAll', 'Sign out all devices')}
        cancelLabel={t('cancelButton', 'Cancel')}
      />
    </Modal>
  );
};

const AdminManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [admins, setAdmins] = useState([]);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const openConfirm = (title, message, onConfirm) => setConfirm({ open: true, title, message, onConfirm });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedAdmin, setSelectedAdmin] = useState(null);
  const [sessionsAdmin, setSessionsAdmin] = useState(null);
  const [statusBusy, setStatusBusy] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  // Default: newest first (`id` autoincrement = creation order), like Users/Nodes.
  const [sort, setSort] = useState({ key: 'id', dir: 'desc' });
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
    enabled: admins.filter((a) => !a.disabled).length,
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
        case 'status': return a.disabled ? 0 : 1;
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

  /** Flip the enabled/disabled state. `status: true` means enabled. */
  const setAdminEnabled = async (admin, enabled) => {
    if (admin.username === currentUsername) {
      addToast(t('adminsCannotDisableSelf', 'You cannot change your own admin status.'), 'warning');
      return;
    }
    setStatusBusy(admin.username);
    try {
      const res = await apiClient.put(
        `/admin/${encodeURIComponent(admin.username)}/status`,
        { status: enabled },
      );
      if (res.data?.success) {
        // The backend also reports how many sessions it revoked on disable.
        const revoked = Number(res.data?.data?.revoked_sessions || 0);
        addToast(
          revoked > 0
            ? `${res.data.msg}. ${t('adminsRevokedSessions', '{{count}} session(s) signed out.', { count: revoked })}`
            : (res.data.msg || t('adminsStatusUpdated', 'Admin status updated.')),
          'success',
        );
        fetchAdmins({ background: true });
      } else {
        addToast(res.data?.msg || t('error'), 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || e.response?.data?.msg || t('error'), 'error');
    } finally {
      setStatusBusy('');
    }
  };

  const askToggleStatus = (admin) => {
    const nextEnabled = !!admin.disabled;
    openConfirm(
      nextEnabled ? t('adminsEnable', 'Enable admin') : t('adminsDisable', 'Disable admin'),
      nextEnabled
        ? t('adminsConfirmEnable', 'Enable admin "{{name}}" so they can log in again?', { name: admin.username })
        : t('adminsConfirmDisable', 'Disable admin "{{name}}"? Every active session will be signed out immediately.', { name: admin.username }),
      () => setAdminEnabled(admin, nextEnabled),
    );
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
      key: 'telegram_id', label: t('adminsTelegram', 'Telegram'), hideOnMobile: true,
      render: (a) => (
        a.telegram_id == null || a.telegram_id === ''
          ? <Badge tone="neutral">{t('adminsTelegramNotLinked', 'Not linked')}</Badge>
          : <Badge tone="success" dot>{t('adminsTelegramLinked', 'Linked')}</Badge>
      ),
    },
    {
      key: 'status', label: t('th_status', 'Status'), sortable: true,
      render: (a) => {
        const isBusy = statusBusy === a.username;
        return (
          <label className="adm-switch" title={a.disabled ? t('adminsEnable', 'Enable admin') : t('adminsDisable', 'Disable admin')}>
            <input
              type="checkbox"
              checked={!a.disabled}
              disabled={isBusy}
              onChange={() => askToggleStatus(a)}
              aria-label={a.disabled
                ? t('adminsEnableAdminAria', 'Enable {{name}}', { name: a.username })
                : t('adminsDisableAdminAria', 'Disable {{name}}', { name: a.username })}
            />
            <span className="adm-switch-track" aria-hidden="true"><span className="adm-switch-thumb" /></span>
            <span className={`adm-switch-label${a.disabled ? '' : ' is-on'}`}>
              {a.disabled ? t('disabled', 'Disabled') : t('enabled', 'Enabled')}
            </span>
          </label>
        );
      },
    },
    {
      key: 'actions', label: t('th_actions', 'Actions'),
      render: (a) => {
        const isSelf = a.username === currentUsername;
        const isBusy = statusBusy === a.username;
        return (
          <span className="dt-actions" role="group" aria-label={`${a.username} ${t('actions', 'Actions')}`}>
            <button type="button" className="dt-icon-btn" title={t('editButton', 'Edit')} aria-label={`${t('editButton', 'Edit')} ${a.username}`} onClick={() => handleEdit(a)}><FiEdit2 size={15} /></button>
            <button type="button" className="dt-icon-btn" title={t('rowSessions', 'Sessions')} aria-label={`${t('rowSessions', 'Sessions')} ${a.username}`} onClick={() => setSessionsAdmin(a)}><FiMonitor size={15} /></button>
            <button
              type="button" className={`dt-icon-btn${a.disabled ? '' : ' is-danger'}`}
              title={a.disabled ? t('adminsEnable', 'Enable admin') : t('adminsDisable', 'Disable admin')}
              aria-label={`${a.disabled ? t('adminsEnable', 'Enable admin') : t('adminsDisable', 'Disable admin')} ${a.username}`}
              disabled={isBusy}
              onClick={() => askToggleStatus(a)}
            >
              <FiPower size={15} />
            </button>
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
  ], [t, currentUsername, statusBusy]);

  const allPageKeys = pagedAdmins.map((a) => String(a.username));
  const allSelected = allPageKeys.length > 0 && allPageKeys.every((k) => selected.has(k));
  const someSelected = allPageKeys.some((k) => selected.has(k));

  return (
    <div id="admins-view" className="view adm-page">
      <div className="adm-head">
        <div>
          <h2 className="adm-title"><FiUserCheck aria-hidden="true" /> {t('admins')}</h2>
          <p className="adm-subtitle">{t('adminsSubtitle', 'Panel operators. Disabling an admin signs them out everywhere immediately.')}</p>
        </div>
        <Button variant="primary" size="sm" icon={<FiPlus size={14} aria-hidden="true" />} onClick={() => setIsAddModalOpen(true)}>
          {t('addNewAdmin', 'Add admin')}
        </Button>
      </div>

      <div className="adm-stats">
        <StatCard label={t('adminsTotal', 'Total admins')} value={adminStats.total} icon={<FiUserCheck />} />
        <StatCard label={t('adminsEnabledCount', 'Enabled')} value={adminStats.enabled} icon={<FiUserCheck />} tone="success" />
        <StatCard label={t('th_users_col', 'Users')} value={adminStats.totalUsers} icon={<FiUsers />} tone="accent" />
      </div>

      <div className="search-pagination-controls">
        <label className="search-field adm-search">
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

      <AdminFormModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSaved={async (msg) => {
          addToast(msg || t('adminCreated', 'Admin created'), 'success');
          setIsAddModalOpen(false);
          fetchAdmins();
        }}
      />
      <AdminFormModal
        isOpen={isEditModalOpen}
        onClose={() => { setIsEditModalOpen(false); setSelectedAdmin(null); }}
        admin={selectedAdmin}
        onSaved={async (msg) => {
          addToast(msg || t('adminUpdated', 'Admin updated'), 'success');
          setIsEditModalOpen(false);
          setSelectedAdmin(null);
          fetchAdmins();
        }}
      />
      <AdminSessionsModal admin={sessionsAdmin} onClose={() => setSessionsAdmin(null)} />
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
