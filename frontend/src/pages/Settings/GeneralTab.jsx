import { useState, useEffect, useCallback } from 'react';
import { FiLink, FiSave, FiCopy } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api';
import { useLive } from '../../context/LiveContext';
import { validateSubscription, buildSubUrl } from '../../utils/settingsHelpers';
import { copyText } from '../../utils/clipboard';

const GeneralTab = () => {
  const { t } = useTranslation();
  const { refreshTick } = useLive();
  const [subPrefix, setSubPrefix] = useState('');
  const [subPath, setSubPath] = useState('');
  const [subError, setSubError] = useState('');
  const [subSaved, setSubSaved] = useState(false);


  const addToast = useCallback((message, type = 'success') => {
    window.dispatchEvent(new CustomEvent('addToast', { detail: { message, type } }));
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const res = await apiClient.get('/server/settings');
      const s = res.data?.data || {};
      setSubPrefix(s.subscription_url_prefix || '');
      setSubPath(s.subscription_path || '');
    } catch { /* noop */ }
  }, []);

  useEffect(() => { loadSettings(); }, [loadSettings, refreshTick]);

  const saveSubscription = async () => {
    const error = validateSubscription(subPrefix, subPath, t);
    if (error) {
      setSubError(error);
      return;
    }
    setSubError('');
    try {
      await apiClient.put('/server/settings/subscription', { prefix: subPrefix, path: subPath });
      setSubSaved(true);
      addToast('Subscription settings saved', 'success');
      setTimeout(() => setSubSaved(false), 2000);
    } catch {
      addToast('Failed to save subscription settings', 'error');
    }
  };

  const copyLink = async () => {
    const url = buildSubUrl(subPrefix, subPath);
    if (!url) return;
    const ok = await copyText(url);
    addToast(ok ? 'Link copied to clipboard' : 'Failed to copy link', ok ? 'success' : 'error');
  };

  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiLink /> Subscription Link</div>
        <div className="setting-card-body">
          <div className="input-group">
            <label>URL prefix</label>
            <input
              value={subPrefix}
              onChange={(e) => setSubPrefix(e.target.value)}
              placeholder="https://domain.tld"
            />
          </div>
          <div className="input-group">
            <label>Path</label>
            <input
              value={subPath}
              onChange={(e) => setSubPath(e.target.value)}
              placeholder="sub"
            />
          </div>
          {subError && <p className="error-message">{subError}</p>}
          <div className="card-actions">
            <button className="btn btn-sm" onClick={saveSubscription}><FiSave size={14} /> {subSaved ? 'Saved' : 'Save'}</button>
            <button className="btn btn-sm btn-secondary" onClick={copyLink}><FiCopy size={14} /> Copy link</button>
          </div>
          {buildSubUrl(subPrefix, subPath) && (
            <div className="sub-url-display">{buildSubUrl(subPrefix, subPath)}</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default GeneralTab;
