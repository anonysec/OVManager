import { useState, useEffect, useMemo } from 'react';
import apiClient from '../services/api';
import { FiActivity, FiRefreshCw } from 'react-icons/fi';

const ACTION_COLORS = {
  create_user: 'ok', delete_user: 'danger', update_user: 'info',
  create_node: 'ok', delete_node: 'danger', update_node: 'info',
  login: 'warn', logout: 'muted', settings: 'info',
};

const fmtTs = (ts) => {
  const d = new Date(ts * 1000);
  return d.toLocaleString();
};

const AuditLog = () => {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actor, setActor] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiClient.get('/activity/', { params: { limit: 200 } });
      if (res.data.success) setEvents(res.data.data || []);
      else setError('Failed to load activity.');
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map(d => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setError(JSON.stringify(detail));
      } else {
        setError(detail || 'Failed to load activity.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    const a = actor.trim().toLowerCase();
    if (!a) return events;
    return events.filter((e) => (e.actor || '').toLowerCase().includes(a));
  }, [events, actor]);

  return (
    <div id="audit-view" className="view">
      <div className="view-header">
        <h2><FiActivity /> Activity &amp; Audit Log</h2>
        <div className="view-header-actions">
          <input
            type="search"
            className="search-input"
            placeholder="Filter by actor…"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            aria-label="Filter by actor"
          />
          <button className="btn btn-sm" onClick={load} title="Refresh"><FiRefreshCw /> Refresh</button>
        </div>
      </div>

      {loading && <div className="table-skeleton">Loading activity…</div>}
      {error && <div className="error-message">{error}</div>}

      {!loading && !error && filtered.length === 0 && (
        <div className="empty-state">
          <div className="empty-illustration" aria-hidden="true">
            <svg viewBox="0 0 120 120" width="110" height="110">
              <rect x="24" y="30" width="72" height="64" rx="6" fill="none" stroke="var(--line)" strokeWidth="2" />
              <line x1="36" y1="48" x2="84" y2="48" stroke="var(--orange)" strokeWidth="3" strokeLinecap="round" />
              <line x1="36" y1="62" x2="72" y2="62" stroke="var(--muted)" strokeWidth="3" strokeLinecap="round" />
              <line x1="36" y1="76" x2="60" y2="76" stroke="var(--muted)" strokeWidth="3" strokeLinecap="round" />
            </svg>
          </div>
          <h3>No activity recorded yet</h3>
          <p>User and node changes will appear here as they happen.</p>
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="list-table-container">
          <table className="list-table audit-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id}>
                  <td data-label="Time">{fmtTs(e.ts)}</td>
                  <td data-label="Actor">{e.actor || 'system'}</td>
                  <td data-label="Action">
                    <span className={`status-pill ${ACTION_COLORS[e.action] || 'muted'}`}>{e.action}</span>
                  </td>
                  <td data-label="Target">{e.target || '—'}</td>
                  <td data-label="Detail" className="audit-detail">{e.detail || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default AuditLog;
