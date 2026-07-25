import { useState, useEffect, useCallback } from 'react';
import { FiArchive, FiUpload, FiRefreshCw, FiDatabase, FiDownload } from 'react-icons/fi';
import apiClient from '../../services/api';
import { useLive } from '../../context/LiveContext';
import { formatBytes } from '../../utils/format';

const BackupTab = () => {
  const { refreshTick } = useLive();
  const [backupMsg, setBackupMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [restoreFile, setRestoreFile] = useState(null);
  const [backupList, setBackupList] = useState([]);

  const loadBackups = useCallback(async () => {
    try {
      const res = await apiClient.get('/maintenance/backup');
      const data = res.data?.data || {};
      if (Array.isArray(data)) {
        setBackupList(data);
      } else if (data.backups) {
        setBackupList(data.backups);
      }
    } catch { /* noop */ }
  }, []);

  useEffect(() => { loadBackups(); }, [loadBackups, refreshTick]);

  const createBackup = async () => {
    setBusy(true);
    setBackupMsg('');
    try {
      const res = await apiClient.post('/maintenance/backup');
      const data = res.data?.data || res.data || {};
      setBackupMsg(data.message || data.msg || 'Backup created successfully');
      addToast(data.message || data.msg || 'Backup created', 'success');
      loadBackups();
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to create backup';
      setBackupMsg(msg);
      addToast(msg, 'error');
    } finally {
      setBusy(false);
    }
  };

  const addToast = (message, type = 'success') => {
    window.dispatchEvent(new CustomEvent('addToast', { detail: { message, type } }));
  };

  const downloadBackup = async () => {
    try {
      const res = await apiClient.get('/maintenance/backup/download', { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'backup.db');
      document.body.appendChild(link);
      link.click();
      link.remove();
      addToast('Backup downloaded', 'success');
    } catch {
      addToast('Failed to download backup', 'error');
    }
  };

  const handleRestore = async () => {
    if (!restoreFile) return;
    setBusy(true);
    setBackupMsg('');
    try {
      const formData = new FormData();
      formData.append('file', restoreFile);
      await apiClient.post('/maintenance/backup/restore', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      addToast('Backup restored successfully', 'success');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Restore failed';
      setBackupMsg(msg);
      addToast(msg, 'error');
    } finally {
      setBusy(false);
    }
  };

  const latestBackup = backupList.length > 0 ? backupList[0] : null;

  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiArchive /> Backup & Restore</div>
        <div className="setting-card-body">
          <div className="card-actions" style={{ marginBottom: 16 }}>
            <button className="btn btn-sm" onClick={createBackup} disabled={busy}><FiUpload size={14} /> Create backup</button>
            <button className="btn btn-sm btn-secondary" onClick={downloadBackup}><FiDownload size={14} /> Download latest</button>
          </div>
          <div className="input-group file-input-wrap">
            <label>Restore from file</label>
            <input type="file" accept=".db" onChange={(e) => setRestoreFile(e.target.files?.[0] || null)} />
          </div>
          <div className="card-actions">
            <button className="btn btn-sm btn-secondary" onClick={handleRestore} disabled={busy || !restoreFile}><FiRefreshCw size={14} /> Restore</button>
          </div>
          {backupMsg && <p className="error-message">{backupMsg}</p>}
          {backupList.length > 0 && (
            <div className="backup-tag"><FiDatabase size={12} /> {backupList.length} backup(s) available</div>
          )}
          {latestBackup && typeof latestBackup === 'object' && (
            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
              Latest: {latestBackup.name || latestBackup.filename || 'backup.db'} {latestBackup.size ? `(${formatBytes(latestBackup.size)})` : ''}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BackupTab;