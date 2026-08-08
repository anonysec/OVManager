import { useState, useEffect, useCallback } from 'react';
import { FiLink, FiEdit2, FiCheck, FiX, FiExternalLink } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import { useLive } from '../../context/LiveContext';
import LoadingButton from '../../components/LoadingButton';
import ErrorState from '../../components/ui/ErrorState';
import '../../components/SettingsStyles.css';

const GeneralTab = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const [urlPath, setUrlPath] = useState('');
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [error, setError] = useState('');

  const loadSettings = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setUrlPath(s.urlpath || '');
    } catch (err) {
      setLoadError(err);
    }
  }, []);

  useEffect(() => { loadSettings(); }, [loadSettings, refreshTick]);

  const handleEdit = () => {
    setEditValue(urlPath);
    setEditing(true);
    setError('');
  };

  const handleCancel = () => {
    setEditing(false);
    setError('');
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const value = editValue.trim().replace(/^\/+|\/+$/g, '');
      if (value && !/^[A-Za-z0-9_-]+$/.test(value)) {
        setError('URL path must contain only letters, numbers, dashes, and underscores');
        return;
      }
      if (value.length > 64) {
        setError('URL path must be 64 characters or less');
        return;
      }
      await apiClient.put('/server/settings/urlpath', { urlpath: value });
      setUrlPath(value);
      setEditing(false);
    } catch (err) {
      setError(err.response?.data?.msg || 'Failed to update URL path');
    } finally {
      setSaving(false);
    }
  };

  const panelUrl = typeof window !== 'undefined' ? `${window.location.origin}/${urlPath}/` : `/${urlPath}/`;

  return (
    <div className="settings-section">
      {loadError && (
        <ErrorState
          title={t('settingsLoadError', 'Failed to load settings')}
          message={loadError.response?.data?.msg || loadError.message || t('settingsLoadErrorDetail', 'Could not fetch server settings.')}
          onRetry={loadSettings}
        />
      )}
      <div className="setting-card">
        <div className="setting-card-header"><FiLink /> Panel URL</div>
        <div className="setting-card-body">
          <div className="urlpath-display">
            <span className="urlpath-label">{t('panelBasePath', 'Base path')}</span>
            <code className="urlpath-value">{urlPath ? `/${urlPath}/` : '/'}</code>
            {!editing && (
              <button type="button" className="urlpath-edit-btn" onClick={handleEdit} aria-label={t('change', 'Change')}>
                <FiEdit2 size={14} />
              </button>
            )}
          </div>
          {editing && (
            <div className="urlpath-edit-form">
              <input
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                placeholder={t('enterPath', 'Enter path (e.g. dash)')}
                className="urlpath-input"
                autoFocus
              />
              {error && <p className="error-message">{error}</p>}
              <div className="urlpath-edit-actions">
                <LoadingButton type="button" className="btn" isLoading={saving} onClick={handleSave}>
                  <FiCheck size={14} /> {t('save', 'Save')}
                </LoadingButton>
                <button type="button" className="btn btn-secondary" onClick={handleCancel}>
                  <FiX size={14} /> {t('cancel', 'Cancel')}
                </button>
              </div>
            </div>
          )}
          <p className="input-hint">
            {urlPath
              ? t('urlpathActive', 'Panel is served at /{path}/... — clear path to serve at root.', { path: urlPath })
              : t('urlpathRoot', 'Panel is served at root (/).')}
          </p>
          <div className="urlpath-preview">
            <span className="preview-label">{t('panelUrl', 'Panel URL')}</span>
            <a href={panelUrl} target="_blank" rel="noopener noreferrer" className="preview-link">
              {panelUrl}
              <FiExternalLink size={12} />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
};

export default GeneralTab;
