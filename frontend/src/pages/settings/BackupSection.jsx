// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { useLive } from '../../context/LiveContext';
import apiClient from '../../services/api';
import ConfirmModal from '../../components/ConfirmModal';
import ErrorState from '../../components/ui/ErrorState';
import EmptyState from '../../components/ui/EmptyState';
import { FiArchive, FiDatabase, FiUpload, FiDownload, FiRefreshCw, FiClock } from 'react-icons/fi';
import { Card, Field } from './shared';
import { formatBytes } from '../../utils/format';
import './BackupSection.css';

const MIN_KEEP = 1;
const MAX_KEEP = 500;
const DEFAULT_TIME = '03:30';

const clampKeep = (value) => {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return 50;
  return Math.max(MIN_KEEP, Math.min(MAX_KEEP, n));
};

const formatAge = (iso, locale) => {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return null;
  const diffSec = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(diffSec);
  try {
    const rtf = new Intl.RelativeTimeFormat(locale || 'en', { numeric: 'auto' });
    if (abs < 3600) return rtf.format(Math.round(diffSec / 60), 'minute');
    if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour');
    return rtf.format(Math.round(diffSec / 86400), 'day');
  } catch {
    return new Date(then).toLocaleString();
  }
};

/* ═══════════════════════════════════════════════════════
   BACKUP (advanced) — Create, download, restore
═══════════════════════════════════════════════════════ */
const BackupSection = () => {
  const { t, i18n } = useTranslation();
  const { refreshTick } = useLive();
  const { addToast } = useToast();
  const [backups, setBackups] = useState([]);
  const [busy, setBusy] = useState('');
  const [restoreFile, setRestoreFile] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  const [autoEnabled, setAutoEnabled] = useState(false);
  const [autoTime, setAutoTime] = useState(DEFAULT_TIME);
  const [autoKeep, setAutoKeep] = useState('50');
  const [offsiteTarget, setOffsiteTarget] = useState('');
  const [telegramBackup, setTelegramBackup] = useState(false);
  const [telegramBackupAvailable, setTelegramBackupAvailable] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);
  const [autoMsg, setAutoMsg] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiClient.get('/server/settings')
      .then((res) => {
        if (cancelled) return;
        const d = res?.data?.data || {};
        setAutoEnabled(d.auto_backup_enabled === true);
        if (typeof d.auto_backup_time === 'string' && d.auto_backup_time) {
          setAutoTime(d.auto_backup_time.slice(0, 5));
        }
        if (d.auto_backup_keep !== undefined && d.auto_backup_keep !== null) {
          setAutoKeep(String(clampKeep(d.auto_backup_keep)));
        }
        if (typeof d.offsite_backup_target === 'string') {
          setOffsiteTarget(d.offsite_backup_target);
        }
        setTelegramBackup(d.telegram_backup_enabled === true);
        setTelegramBackupAvailable(d.telegram_backup_available === true);
      })
      .catch(() => { /* keep the defaults; the card still renders */ });
    return () => { cancelled = true; };
  }, []);

  const saveAuto = async () => {
    setAutoSaving(true);
    setAutoMsg(null);
    const keep = clampKeep(autoKeep);
    try {
      const r = await apiClient.put('/server/settings/bot', {
        auto_backup_enabled: autoEnabled,
        auto_backup_time: autoTime || DEFAULT_TIME,
        auto_backup_keep: keep,
        offsite_backup_target: offsiteTarget.trim(),
        telegram_backup_enabled: telegramBackup,
      });
      if (r?.data?.success === false) {
        setAutoMsg({ type: 'error', text: r.data?.msg || t('error', 'Failed') });
      } else {
        setAutoKeep(String(keep));
        setOffsiteTarget((r?.data?.data?.offsite_backup_target ?? offsiteTarget.trim()));
        setTelegramBackup(r?.data?.data?.telegram_backup_enabled === true);
        setTelegramBackupAvailable(r?.data?.data?.telegram_backup_available === true);
        setAutoMsg({ type: 'success', text: r?.data?.msg || t('backupAutoSaved', 'Automatic backup settings saved.') });
      }
    } catch (e) {
      setAutoMsg({ type: 'error', text: e.response?.data?.detail || e.response?.data?.msg || t('error', 'Failed') });
    } finally {
      setAutoSaving(false);
    }
  };

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
      const a = document.createElement('a'); a.href = url; a.download = backups[0]?.name || 'ovmanager-backup.ovmbak';
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { addToast(t('error', 'Download failed'), 'error'); }
  };

  const doRestore = async () => {
    if (!restoreFile) return;
    if (!restoreFile.name.endsWith('.ovmbak') && !restoreFile.name.endsWith('.db')) {
      addToast(t('backupMustBeDb', 'Backup file must be an .ovmbak bundle or legacy .db file.'), 'error');
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
      message: t('confirmRestoreFile', 'Restore from "{{name}}"? OVManager will verify it and create a safety backup before replacing current data.', { name: restoreFile.name }),
      onConfirm: doRestore,
    });
  };

  const newestBackup = backups[0];
  const newestAge = newestBackup?.modified ? formatAge(newestBackup.modified, i18n.language) : null;

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
        </div>
        {loadError && backups.length === 0 ? (
          <ErrorState title={t('loadError', 'Could not load data')} message={t('loadErrorDetail', 'Could not reach backup list.')} onRetry={load} retryLabel={t('retry', 'Retry')} />
        ) : backups.length === 0 ? (
          <EmptyState title={t('noBackups', 'No backups yet')} description={t('noBackupsBody', 'Create your first backup to protect panel data.')} />
        ) : (
          <div className="sp-backup-list">
            {backups.map(b => (
              <div key={b.name} className="sp-backup-row">
                <FiDatabase size={13} aria-hidden="true" />
                <span className="sp-backup-name">{b.name}</span>
                {b.verified === true && <span className="sp-backup-size">{t('backupVerified', 'Verified')}</span>}
                {b.verified === false && <span className="sp-backup-size">{t('backupInvalid', 'Invalid')}</span>}
                {b.size && <span className="sp-backup-size">{formatBytes(b.size)}</span>}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={t('backupAutoTitle', 'Automatic backups')} icon={FiClock}>
        <p className="sp-hint sp-mb-12">
          {t('backupAutoHint', 'Off by default. When enabled, the panel writes a database backup every day at this time and keeps only the newest N.')}
        </p>

        <Field label={t('backupAutoToggle', 'Enable automatic backups')} horizontal inputId="backup-auto-enabled">
          <label className="sp-toggle">
            <input
              id="backup-auto-enabled"
              type="checkbox"
              checked={autoEnabled}
              disabled={autoSaving}
              aria-label={t('backupAutoToggle', 'Enable automatic backups')}
              onChange={(e) => setAutoEnabled(e.target.checked)}
            />
            <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
          </label>
        </Field>

        <div className="sp-two-col">
          <Field label={t('backupAutoTime', 'Backup time')} inputId="backup-auto-time">
            <input
              id="backup-auto-time"
              className="sp-input"
              type="time"
              value={autoTime}
              disabled={!autoEnabled || autoSaving}
              onChange={(e) => setAutoTime(e.target.value)}
            />
          </Field>
          <Field
            label={t('backupAutoKeep', 'Keep newest backups')}
            hint={t('backupAutoKeepHint', 'How many daily backups to keep (1–500). Older ones are removed.')}
            inputId="backup-auto-keep"
          >
            <input
              id="backup-auto-keep"
              className="sp-input"
              type="number"
              min={MIN_KEEP}
              max={MAX_KEEP}
              value={autoKeep}
              disabled={autoSaving}
              onChange={(e) => setAutoKeep(e.target.value)}
            />
          </Field>
        </div>

        <Field
          label={t('offsiteTarget', 'Offsite copy target')}
          hint={t('offsiteTargetHint', 'Optional. After each automatic backup, the newest file is copied here with rsync (or scp). Format: user@server:/path — the target folder must already exist and SSH key login must work.')}
          inputId="backup-offsite-target"
        >
          <input
            id="backup-offsite-target"
            className="sp-input"
            type="text"
            dir="ltr"
            placeholder={t('offsiteTargetPlaceholder', 'backup@server:/backups/panel')}
            value={offsiteTarget}
            disabled={autoSaving}
            autoComplete="off"
            spellCheck="false"
            onChange={(e) => setOffsiteTarget(e.target.value)}
          />
        </Field>

        <Field
          label={t('telegramBackup', 'Encrypted Telegram copy')}
          hint={telegramBackupAvailable
            ? t('telegramBackupHint', 'Send each scheduled backup to the configured owner chat after encrypting it on this server. Keep BACKUP_ENCRYPT_KEY somewhere outside this server for disaster recovery.')
            : t('telegramBackupUnavailable', 'Add BACKUP_ENCRYPT_KEY to the server configuration before enabling Telegram backups.')}
          horizontal
          inputId="backup-telegram-enabled"
        >
          <label className="sp-toggle">
            <input
              id="backup-telegram-enabled"
              type="checkbox"
              checked={telegramBackup}
              disabled={autoSaving || !telegramBackupAvailable}
              onChange={(e) => setTelegramBackup(e.target.checked)}
            />
            <span className="sp-toggle-track"><span className="sp-toggle-thumb" /></span>
          </label>
        </Field>

        {newestAge && (
          <p className="sp-hint sp-mt-12">
            {t('backupAutoNewest', 'Newest backup: {{name}} ({{age}})', { name: newestBackup.name, age: newestAge })}
          </p>
        )}

        <div className="sp-btn-group sp-mt-18">
          <button className="btn btn-sm" disabled={autoSaving} aria-busy={autoSaving} onClick={saveAuto}>
            {autoSaving ? <span className="button-spinner" aria-hidden="true" /> : t('backupAutoSave', 'Save')}
          </button>
        </div>

        {autoMsg && (
          <p className={`bs-auto-msg bs-auto-msg--${autoMsg.type}`} role={autoMsg.type === 'error' ? 'alert' : 'status'}>
            {autoMsg.text}
          </p>
        )}
      </Card>

      <Card title={t('restoreSection', 'Restore from File')} icon={FiArchive}>
        <p className="sp-hint sp-mb-12">{t('restoreHint', 'Select an .ovmbak bundle or legacy .db backup. This overwrites current data and asks for confirmation.')}</p>
        <div className="sp-field">
          <label className="sr-only" htmlFor="sp-restore-file">{t('selectBackupFile', 'Select backup file')}</label>
          <input id="sp-restore-file" type="file" accept=".ovmbak,.db" onChange={e => setRestoreFile(e.target.files?.[0] || null)} className="sp-file-input" aria-label={t('selectBackupFile', 'Select backup file')} />
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
