import { FiLink, FiSave, FiCopy } from 'react-icons/fi';
import { buildSubUrl } from '../../utils/settingsHelpers';

const GeneralTab = ({ t, subPrefix, subPath, subError, subSaved, setSubPrefix, setSubPath, copyLink, saveSubscription }) => {
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