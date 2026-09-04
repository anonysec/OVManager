import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { FiDatabase, FiDownload, FiUpload, FiRefreshCw } from 'react-icons/fi';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import LoadingButton from '../components/LoadingButton';
import ConfirmModal from '../components/ConfirmModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import DataTable from '../components/ui/DataTable';
import { formatBytes } from '../utils/format';

const Maintenance = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [backups, setBackups] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [restoreFile, setRestoreFile] = useState(null);
  const [isRestoreLoading, setIsRestoreLoading] = useState(false);
  const [isCreateLoading, setIsCreateLoading] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const openConfirm = (title, msg, onConfirm) => setConfirm({ open: true, title, message: msg, onConfirm });
  const closeConfirm = () => setConfirm(c => ({ ...c, open: false }));

  const fetchBackups = useCallback(async ({ background = false } = {}) => {
    if (!background) setIsLoading(true);
    setLoadError(false);
    try {
      const response = await apiClient.get('/maintenance/backup/list');
      if (response.data.success) {
        setBackups(response.data.data || []);
      } else {
        setLoadError(true);
      }
    } catch {
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBackups();
  }, [fetchBackups]);

  const handleCreateBackup = async () => {
    setIsCreateLoading(true);
    try {
      const response = await apiClient.post('/maintenance/backup');
      if (response.data?.success) {
        addToast(response.data.msg || t('backupCreated', 'Backup created.'), 'success');
      } else {
        addToast(response.data?.msg || t('backupFailed', 'Backup failed.'), 'error');
      }
      fetchBackups({ background: true });
    } catch (e) {
      addToast(e.response?.data?.detail || e.response?.data?.msg || t('backupFailed', 'Backup failed.'), 'error');
    } finally {
      setIsCreateLoading(false);
    }
  };

  const handleDownloadLatest = async () => {
    try {
      const response = await apiClient.get('/maintenance/backup/download', {
        responseType: 'blob',
      });
      const blob = new Blob([response.data], { type: 'application/octet-stream' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = backups[0]?.name || 'ovmanager-backup.db';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      addToast(e.response?.data?.detail || t('downloadFailed', 'Download failed.'), 'error');
    }
  };

  const doRestoreFromServer = async (backupName) => {
    setIsRestoreLoading(true);
    try {
      const form = new FormData();
      form.append('restore_from_server', backupName);
      const response = await apiClient.post('/maintenance/backup/restore', form);
      if (response.data?.success) {
        addToast(response.data.msg || t('restored', 'Restore complete.'), 'success');
      } else {
        addToast(response.data?.msg || t('restoreFailed', 'Restore failed.'), 'error');
      }
      fetchBackups({ background: true });
    } catch (e) {
      addToast(e.response?.data?.detail || e.response?.data?.msg || t('restoreFailed', 'Restore failed.'), 'error');
    } finally {
      setIsRestoreLoading(false);
    }
  };

  const handleRestoreFromServer = (backupName) => {
    openConfirm(
      t('restoreButton', 'Restore'),
      t('confirmRestoreServer', 'Restore from "{{name}}"? This will overwrite current data.', { name: backupName }),
      () => doRestoreFromServer(backupName)
    );
  };

  const doRestoreFile = async () => {
    if (!restoreFile) {
      addToast(t('selectBackupFile', 'Please select a backup file.'), 'warning');
      return;
    }
    if (!restoreFile.name.endsWith('.db')) {
      addToast(t('backupMustBeDb', 'Backup file must be a .db file.'), 'error');
      return;
    }
    if (restoreFile.size > 100 * 1024 * 1024) {
      addToast(t('fileTooLarge', 'File too large (max 100 MB).'), 'error');
      return;
    }
    setIsRestoreLoading(true);
    try {
      const formData = new FormData();
      formData.append('file', restoreFile);
      const response = await apiClient.post('/maintenance/backup/restore', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (response.data?.success) {
        addToast(response.data.msg || t('restored', 'Restore complete.'), 'success');
        setRestoreFile(null);
      } else {
        addToast(response.data?.msg || t('restoreFailed', 'Restore failed.'), 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || e.response?.data?.msg || t('restoreFailed', 'Restore failed.'), 'error');
    } finally {
      setIsRestoreLoading(false);
    }
  };

  const handleRestoreFileAsk = () => {
    if (!restoreFile) {
      addToast(t('selectBackupFile', 'Please select a backup file.'), 'warning');
      return;
    }
    openConfirm(
      t('restoreButton', 'Restore'),
      t('confirmRestoreFile', 'Restore from "{{name}}"? This will overwrite current data.', { name: restoreFile.name }),
      doRestoreFile
    );
  };

  const columns = [
    {
      key: 'name', label: t('fileName', 'File'), sortable: true,
      render: (b) => (
        <span className="dt-cell-main">
          <span className="dt-avatar" aria-hidden="true"><FiDatabase size={14} /></span>
          <span className="dt-cell-title" title={b.name}>{b.name}</span>
        </span>
      ),
    },
    {
      key: 'size', label: t('fileSize', 'Size'), sortable: true, className: 'dt-num',
      render: (b) => formatBytes(b.size),
    },
    {
      key: 'modified', label: t('modified', 'Modified'), sortable: true, hideOnMobile: true,
      render: (b) => { try { return new Date(b.modified).toLocaleString(); } catch { return b.modified || '—'; } },
    },
    {
      key: 'actions', label: t('actions', 'Actions'),
      render: (b) => (
        <span className="dt-actions">
          <button type="button" className="btn btn-secondary btn-sm" disabled={isRestoreLoading} onClick={() => handleRestoreFromServer(b.name)}>
            <FiUpload size={13} /> {t('restoreButton', 'Restore')}
          </button>
        </span>
      ),
    },
  ];

  return (
    <div id="maintenance-view" className="view">
      <div className="view-header">
        <h2>{t('navMaintenance', 'Maintenance')}</h2>
        <div className="view-header-actions">
          <Link to="/settings" className="btn btn-secondary btn-sm">{t('navSettings', 'Settings')}</Link>
          <LoadingButton isLoading={isCreateLoading} onClick={handleCreateBackup} className="btn btn-primary btn-sm">
            <FiDatabase size={13} /> {t('createBackup', 'Create backup')}
          </LoadingButton>
          {backups.length > 0 && (
            <button type="button" onClick={handleDownloadLatest} className="btn btn-secondary btn-sm">
              <FiDownload size={13} /> {t('downloadLatest', 'Download latest')}
            </button>
          )}
        </div>
      </div>

      <div className="user-stats-row" role="region" aria-label={t('backupTitle', 'Backups')}>
        <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
          <span className="us-ico"><FiDatabase aria-hidden="true" /></span>
          <span className="us-body">
            <span className="us-label">{t('backupTitle', 'Backups')}</span>
            <span className="us-value">{backups.length}</span>
          </span>
        </div>
      </div>

      <div className="sp-cards" style={{ marginBottom: 16 }}>
        <div className="sp-card">
          <h3 style={{ margin: '0 0 8px', fontSize: '0.95rem' }}>{t('restoreSection', 'Restore from file')}</h3>
          <p className="sp-hint" style={{ marginBottom: 12 }}>{t('restoreHint', 'Select a .db backup file to restore. This overwrites current data and asks for confirmation.')}</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <label className="sp-file-label">
              <span className="sr-only">{t('selectBackupFile', 'Select backup file')}</span>
              <input
                type="file"
                accept=".db"
                onChange={(e) => setRestoreFile(e.target.files?.[0] || null)}
                disabled={isRestoreLoading}
                aria-label={t('selectBackupFile', 'Select backup file')}
              />
            </label>
            <LoadingButton isLoading={isRestoreLoading} onClick={handleRestoreFileAsk} className="btn btn-secondary btn-sm" disabled={!restoreFile}>
              <FiRefreshCw size={13} /> {t('restoreButton', 'Restore')}
            </LoadingButton>
            {restoreFile && <span className="dt-cell-sub">{restoreFile.name} · {formatBytes(restoreFile.size)}</span>}
          </div>
        </div>
      </div>

      {isLoading ? (
        <DataTable columns={columns} rows={[]} loading />
      ) : loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchBackups()} retryLabel={t('retry')} />
      ) : backups.length === 0 ? (
        <EmptyState
          title={t('noBackups', 'No backups yet')}
          description={t('noBackupsBody', 'Create your first backup to protect panel data.')}
          actionLabel={t('createBackup', 'Create backup')}
          onAction={handleCreateBackup}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={backups}
          rowKey={(r) => r.name}
          page={1}
          pageSize={backups.length}
          total={backups.length}
          onPageChange={null}
          caption={t('backupHistory', 'Backup history')}
        />
      )}

      <ConfirmModal open={confirm.open} onClose={closeConfirm} onConfirm={confirm.onConfirm || (() => {})} title={confirm.title} message={confirm.message} danger confirmLabel={t('restoreButton', 'Restore')} cancelLabel={t('cancelButton', 'Cancel')} />
    </div>
  );
};

export default Maintenance;
