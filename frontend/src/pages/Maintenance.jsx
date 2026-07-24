import { useEffect, useState } from 'react';
import { FiDatabase, FiRefreshCw, FiUpload, FiDownload } from 'react-icons/fi';
import apiClient from '../services/api';
import { useTranslation } from 'react-i18next';
import LoadingButton from '../components/LoadingButton';

const Maintenance = () => {
  const { t } = useTranslation();
  const [backups, setBackups] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [restoreFile, setRestoreFile] = useState(null);
  const [isRestoreLoading, setIsRestoreLoading] = useState(false);
  const [message, setMessage] = useState('');

  const fetchBackups = async () => {
    setIsLoading(true);
    try {
      const response = await apiClient.get('/maintenance/backup/list');
      if (response.data.success) {
        setBackups(response.data.data || []);
      }
    } catch (error) {
      console.error('Error fetching backups:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchBackups();
  }, []);

  const handleCreateBackup = async () => {
    setMessage('');
    try {
      const response = await apiClient.post('/maintenance/backup');
      setMessage(response.data.msg || 'Backup created.');
      fetchBackups();
    } catch (error) {
      setMessage(error.response?.data?.msg || 'Backup failed.');
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
      link.download = 'ov-panel-backup.db';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error.response?.data?.detail || 'Download failed.');
    }
  };

  const handleFileChange = (e) => {
    setRestoreFile(e.target.files[0] || null);
  };

  const handleRestoreFromServer = async (backupName) => {
    if (!window.confirm(`Restore from backup "${backupName}"? This will overwrite current data.`)) return;
    setIsRestoreLoading(true);
    setMessage('');
    try {
      const form = new FormData();
      form.append('file', new File([], backupName));
      form.append('restore_from_server', backupName);
      const response = await apiClient.post('/maintenance/backup/restore', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setMessage(response.data.msg || 'Restore complete.');
      fetchBackups();
    } catch (error) {
      setMessage(error.response?.data?.msg || 'Restore failed.');
    } finally {
      setIsRestoreLoading(false);
    }
  };

  const handleRestore = async () => {
    if (!restoreFile) {
      setMessage('Please select a backup file.');
      return;
    }
    setIsRestoreLoading(true);
    setMessage('');
    try {
      const formData = new FormData();
      formData.append('file', restoreFile);
      const response = await apiClient.post('/maintenance/backup/restore', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setMessage(response.data.msg || 'Restore complete.');
    } catch (error) {
      setMessage(error.response?.data?.msg || 'Restore failed.');
    } finally {
      setIsRestoreLoading(false);
      setRestoreFile(null);
    }
  };

  return (
    <div id="maintenance-view" className="view">
      <h2>{t('settingsTitle')}</h2>

      <div className="stats-grid" style={{ marginBottom: '30px' }}>
        <div className="stat-card">
          <div className="stat-icon"><FiDatabase /></div>
          <div className="stat-content">
            <div className="stat-label">{t('backupTitle')}</div>
            <div className="stat-value">{backups.length}</div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <h3 style={{ marginBottom: '15px' }}>{t('backupActions')}</h3>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <LoadingButton isLoading={isLoading} onClick={handleCreateBackup} className="btn">
            {t('createBackup')}
          </LoadingButton>
          <button onClick={handleDownloadLatest} className="btn">
            {t('downloadLatest')}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <h3 style={{ marginBottom: '15px' }}>{t('restoreSection')}</h3>
        <div style={{ marginBottom: '15px' }}>
          <input
            type="file"
            accept=".db"
            onChange={handleFileChange}
            disabled={isRestoreLoading}
          />
        </div>
        <LoadingButton isLoading={isRestoreLoading} onClick={handleRestore} className="btn" style={{ marginBottom: '15px' }}>
          {t('restoreButton')}
        </LoadingButton>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: '15px' }}>{t('backupHistory')}</h3>
        {backups.length === 0 ? (
          <p>{t('noBackups')}</p>
        ) : (
          <table className="list-table">
            <thead>
              <tr>
                <th>{t('fileName')}</th>
                <th>{t('fileSize')}</th>
                <th>{t('modified')}</th>
                <th>{t('actions')}</th>
              </tr>
            </thead>
            <tbody>
              {backups.map((backup) => (
                <tr key={backup.name}>
                  <td>{backup.name}</td>
                  <td>{(backup.size / 1024).toFixed(1)} KB</td>
                  <td>{new Date(backup.modified).toLocaleString()}</td>
                  <td>
                    <button onClick={() => handleRestoreFromServer(backup.name)} className="btn">
                      {t('restoreButton')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {message && <div className="notification" style={{ marginTop: '20px' }}>{message}</div>}
    </div>
  );
};

export default Maintenance;