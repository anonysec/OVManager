import { FiArchive, FiUpload, FiRefreshCw, FiDatabase } from 'react-icons/fi';

const BackupTab = ({ t, backups, backupFile, setBackupFile, backupMsg, handleRestore, createBackup, downloadBackup, busy, restoreFile, setRestoreFile }) => {
  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiArchive /> Backup & Restore</div>
        <div className="setting-card-body">
          <div className="card-actions" style={{ marginBottom: 16 }}>
            <button className="btn btn-sm" onClick={createBackup} disabled={busy}><FiUpload size={14} /> Create backup</button>
            <button className="btn btn-sm btn-secondary" onClick={downloadBackup}><FiUpload size={14} /> Download latest</button>
          </div>
          <div className="input-group file-input-wrap">
            <label>Restore from file</label>
            <input type="file" accept=".db" onChange={(e) => setRestoreFile(e.target.files?.[0] || null)} />
          </div>
          <div className="card-actions">
            <button className="btn btn-sm btn-secondary" onClick={handleRestore} disabled={busy || !restoreFile}><FiRefreshCw size={14} /> Restore</button>
          </div>
          {backupMsg && <p className="error-message">{backupMsg}</p>}
          {backups.length > 0 && (
            <div className="backup-tag"><FiDatabase size={12} /> {backups.length} backup(s) available</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BackupTab;