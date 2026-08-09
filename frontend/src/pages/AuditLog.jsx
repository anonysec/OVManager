import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { FiActivity, FiRefreshCw } from 'react-icons/fi';
import { fmtDateTime } from '../utils/time';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import PanelSkeleton from '../components/ui/PanelSkeleton';

const ACTION_COLORS = {
  'user.create': 'ok', 'user.delete': 'danger', 'user.update': 'info',
  'user.status': 'info', 'user.disconnect': 'warn', 'user.reset': 'info',
  'node.create': 'ok', 'node.delete': 'danger', 'node.update': 'info',
  'maintenance.backup': 'info', 'maintenance.restore': 'warn',
};

const AuditLog = () => {
  const { t } = useTranslation();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actor, setActor] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiClient.get('/activity/', { params: { limit: 200 } });
      if (res.data.success) setEvents(res.data.data || []);
      else setError(t('failedToLoad', 'Failed to load activity.'));
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((d) => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setError(JSON.stringify(detail));
      } else {
        setError(detail || t('failedToLoad', 'Failed to load activity.'));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const a = actor.trim().toLowerCase();
    if (!a) return events;
    return events.filter((e) => (e.actor || '').toLowerCase().includes(a));
  }, [events, actor]);

  return (
    <div id="audit-view" className="view">
      <div className="view-header">
        <h2><FiActivity /> {t('navAudit', 'Audit Log')}</h2>
        <div className="view-header-actions">
          <input
            type="search"
            className="search-input"
            placeholder={t('searchByUsername', 'Filter by actor…')}
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            aria-label={t('searchByUsername', 'Filter by actor')}
          />
          <button className="btn btn-sm" onClick={load} title={t('refresh', 'Refresh')}>
            <FiRefreshCw /> {t('refresh', 'Refresh')}
          </button>
        </div>
      </div>

      {loading && <PanelSkeleton lines={6} label={t('loading', 'Loading…')} />}

      {error && !loading && (
        <ErrorState title={t('error', 'Error')} message={error} onRetry={load} retryLabel={t('retry', 'Retry')} />
      )}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title={t('noActivity', 'No activity recorded yet')}
          description={t('activityWillAppear', 'User and node changes will appear here as they happen.')}
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="list-table-container">
          <table className="list-table audit-table">
            <thead>
              <tr>
                <th>{t('th_lastOnline', 'Time')}</th>
                <th>{t('th_admin', 'Actor')}</th>
                <th>{t('status', 'Action')}</th>
                <th>{t('user', 'Target')}</th>
                <th>{t('node', 'Detail')}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id}>
                  <td data-label={t('th_lastOnline', 'Time')}>{e.ts ? fmtDateTime(new Date(e.ts * 1000).toISOString()) : '—'}</td>
                  <td data-label={t('th_admin', 'Actor')}>{e.actor || 'system'}</td>
                  <td data-label={t('status', 'Action')}>
                    <span className={`status-pill ${ACTION_COLORS[e.action] || 'muted'}`}>{e.action}</span>
                  </td>
                  <td data-label={t('user', 'Target')}>{e.target || '—'}</td>
                  <td data-label={t('node', 'Detail')} className="audit-detail">{e.detail || '—'}</td>
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
