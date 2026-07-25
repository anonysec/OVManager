import { FiShield } from 'react-icons/fi';

const SecurityTab = ({ t, secHours, setSecHours, sec }) => {
  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiShield /> Security Summary</div>
        <div className="setting-card-body">
          <div className="card-actions" style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600, alignSelf: 'center' }}>Hours:</label>
            {[4, 8, 12, 24, 48].map(h => (
              <button key={h} className={`btn btn-sm ${secHours === h ? '' : 'btn-secondary'}`} onClick={() => setSecHours(h)}>{h}h</button>
            ))}
          </div>
          <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            <div className="metric-mini"><div className="metric-label">Auth Errors</div><div className={`metric-value ${sec.auth_errors > 0 ? 'danger' : ''}`}>{sec.auth_errors || 0}</div></div>
            <div className="metric-mini"><div className="metric-label">Rejects</div><div className={`metric-value ${sec.rejects > 0 ? 'danger' : ''}`}>{sec.rejects || 0}</div></div>
            <div className="metric-mini"><div className="metric-label">Stale</div><div className={`metric-value ${sec.stale_markers > 0 ? 'danger' : ''}`}>{sec.stale_markers || 0}</div></div>
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Last {secHours} hours</p>
        </div>
      </div>
    </div>
  );
};

export default SecurityTab;