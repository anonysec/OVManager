import { useState, useEffect, useCallback } from 'react';
import { FiShield } from 'react-icons/fi';
import apiClient from '../../services/api';
import { useLive } from '../../context/LiveContext';

const SecurityTab = () => {

  const { refreshTick } = useLive();
  const [secHours, setSecHours] = useState(24);
  const [sec, setSec] = useState(null);

  const loadSecurity = useCallback(async () => {
    try {
      const res = await apiClient.get(`/security/summary?hours=${secHours}`);
      setSec(res.data?.data || null);
    } catch { /* noop */ }
  }, [secHours]);

  useEffect(() => { loadSecurity(); }, [loadSecurity, refreshTick]);

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
          {sec ? (
            <>
              <div className="metric-mini-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                <div className="metric-mini"><div className="metric-label">Auth Errors</div><div className={`metric-value ${sec.auth_errors > 0 ? 'danger' : ''}`}>{sec.auth_errors || 0}</div></div>
                <div className="metric-mini"><div className="metric-label">Rejects</div><div className={`metric-value ${sec.rejects > 0 ? 'danger' : ''}`}>{sec.rejects || 0}</div></div>
                <div className="metric-mini"><div className="metric-label">Stale</div><div className={`metric-value ${sec.stale_markers > 0 ? 'danger' : ''}`}>{sec.stale_markers || 0}</div></div>
              </div>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Last {secHours} hours</p>
            </>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--muted)' }}>No security data available</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default SecurityTab;
