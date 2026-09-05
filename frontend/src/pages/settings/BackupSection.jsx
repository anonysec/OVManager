// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useToast } from '../../context/ToastContext';
import { useLive } from '../../context/LiveContext';
import apiClient from '../../services/api';
import ConfirmModal from '../../components/ConfirmModal';
import ErrorState from '../../components/ui/ErrorState';
import EmptyState from '../../components/ui/EmptyState';
import { FiArchive, FiDatabase, FiUpload, FiDownload, FiRefreshCw } from 'react-icons/fi';
import { Card } from './shared';
import { formatBytes } from '../../utils/format';

/* ═══════════════════════════════════════════════════════
   BACKUP (advanced) — Create, download, restore
═══════════════════════════════════════════════════════ */
const BackupSection = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [backups, setBackups] = useState([]);
  const [busy, setBusy] = useState('');
  const [restoreFile, setRestoreFile] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  const load = useCallback(async () => {
    try {
      setLoadError(false);
      const r = await apiClient.get('/maintenance/backup/list');
      if (Array.isArray(r.data?.data)) setBackups(r.data.data);
    }
    catch { setLoadError(true); }
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  const create = async () => {
    setBusy('create');
    try {
      const r = await apiClient.post('/maintenance/backup');
      addToast(r.data?.msg || t('createBackup', 'Backup created'), 'success');
      load();
    } catch (e) { addToast(e.response?.data?.detail || e.response?.data?.msg || t('error', 'Failed'), 'error'); }
    finally { setBusy(''); }
  };

  const download = async () => {
    try {
      const r = await apiClient.get('/maintenance/backup/download', { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a'); a.href = url; a.download = backups[0]?.name || 'ovmanager-backup.db';
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { addToast(t('error', 'Download failed'), 'error'); }
  };

  const doRestore = async () => {
    if (!restoreFile) return;
    if (!restoreFile.name.endsWith('.db')) {
      addToast(t('backupMustBeDb', 'Backup file must be a .db file.'), 'error');
      return;
    }
    setBusy('restore');
    try {
      const fd = new FormData(); fd.append('file', restoreFile);
      const r = await apiClient.post('/maintenance/backup/restore', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      if (r.data?.success) {
        addToast(r.data.msg || t('restored', 'Restored successfully'), 'success');
        setRestoreFile(null);
      } else {
        addToast(r.data?.msg || t('error', 'Restore failed'), 'error');
      }
    } catch (e) { addToast(e.response?.data?.detail || e.response?.data?.msg || t('error', 'Restore failed'), 'error'); }
    finally { setBusy(''); }
  };

  const askRestore = () => {
    if (!restoreFile) return;
    setConfirm({
      open: true,
      title: t('restoreButton', 'Restore'),
      message: t('confirmRestoreFile', 'Restore from "{{name}}"? This will overwrite current data.', { name: restoreFile.name }),
      onConfirm: doRestore,
    });
  };

  return (
    <div className="sp-cards">
      <Card title={t('backupTitle', 'Database Backup')} icon={FiDatabase}>
        <div className="sp-btn-group sp-mb-16">
          <button className="btn btn-sm" disabled={!!busy} aria-busy={busy === 'create'} onClick={create}>
            {busy === 'create' ? <span className="button-spinner" aria-hidden="true" /> : <><FiUpload size={13} aria-hidden="true" /> {t('createBackup', 'Create backup')}</>}
          </button>
          {backups.length > 0 && (
            <button className="btn btn-sm btn-secondary" onClick={download}>
              <FiDownload size={13} /> {t('downloadLatest', 'Download latest')}
            </button>
          )}
          <Link to="/maintenance" className="btn btn-sm btn-secondary">{t('viewAll', 'View all')}</Link>
        </div>
        {loadError && backups.length === 0 ? (
          <ErrorState title={t('loadError', 'Could not load data')} message={t('loadErrorDetail', 'Could not reach backup list.')} onRetry={load} retryLabel={t('retry', 'Retry')} />
        ) : backups.length === 0 ? (
          <EmptyState title={t('noBackups', 'No backups yet')} description={t('noBackupsBody', 'Create your first backup to protect panel data.')} />
        ) : (
          <div className="sp-backup-list">
            {backups.slice(0, 8).map(b => (
              <div key={b.name} className="sp-backup-row">
                <FiDatabase size={13} aria-hidden="true" />
                <span className="sp-backup-name">{b.name}</span>
                {b.size && <span className="sp-backup-size">{formatBytes(b.size)}</span>}
              </div>
            ))}
            {backups.length > 8 && (
              <Link to="/maintenance" className="sp-viewall">{t('showingMore', 'Showing 8 of {{total}} — view all', { total: backups.length })}</Link>
            )}
          </div>
        )}
      </Card>

      <Card title={t('restoreSection', 'Restore from File')} icon={FiArchive}>
        <p className="sp-hint sp-mb-12">{t('restoreHint', 'Select a .db backup file to restore. This overwrites current data and asks for confirmation.')}</p>
        <div className="sp-field">
          <label className="sr-only" htmlFor="sp-restore-file">{t('selectBackupFile', 'Select backup file')}</label>
          <input id="sp-restore-file" type="file" accept=".db" onChange={e => setRestoreFile(e.target.files?.[0] || null)} className="sp-file-input" aria-label={t('selectBackupFile', 'Select backup file')} />
        </div>
        <button className="btn btn-sm" disabled={!restoreFile || !!busy} aria-busy={busy === 'restore'} onClick={askRestore}>
          {busy === 'restore' ? <span className="button-spinner" aria-hidden="true" /> : <><FiRefreshCw size={13} aria-hidden="true" /> {t('restoreButton', 'Restore')}</>}
        </button>
      </Card>
      <ConfirmModal open={confirm.open} onClose={closeConfirm} onConfirm={confirm.onConfirm || (() => {})} title={confirm.title} message={confirm.message} danger confirmLabel={t('restoreButton', 'Restore')} cancelLabel={t('cancelButton', 'Cancel')} />
    </div>
  );
};

export default BackupSection;
