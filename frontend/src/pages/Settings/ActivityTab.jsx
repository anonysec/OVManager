import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FiActivity } from 'react-icons/fi';
import apiClient from '../../services/api';
import ErrorState from '../../components/ui/ErrorState';
import EmptyState from '../../components/ui/EmptyState';

const ActivityTab = () => {
  const { t } = useTranslation();
  const [activity, setActivity] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadActivity = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await apiClient.get('/activity/?limit=25');
      const data = res.data?.data || [];
      setActivity(Array.isArray(data) ? data : []);
    } catch {
      setError(t('failedToLoad', 'Failed to load data'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { loadActivity(); }, [loadActivity]);

  return (
    <div className="settings-section">
      {error && (
        <ErrorState
          title={t('error', 'Error')}
          message={error}
          onRetry={loadActivity}
        />
      )}
      {!error && (
        <div className="setting-card">
          <div className="setting-card-header"><FiActivity /> Recent Activity</div>
          <div className="setting-card-body">
            {activity.length === 0 ? (
              <EmptyState
                title={t('noActivity', 'No activity yet')}
                description={t('activityWillAppear', 'System actions will appear here')}
              />
            ) : (
              activity.slice(0, 30).map((e) => {
                const ts = e.ts ? new Date(e.ts * 1000).toISOString() : null;
                const isDel = e.action === 'delete_user' || e.action === 'delete_node';
                return (
                  <div key={e.id} className="feed-item">
                    <span className={`feed-badge ${isDel ? 'danger' : 'muted'}`}>
                      {e.action?.replace(/_/g, ' ')}
                    </span>
                    <div className="feed-content">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <span className="feed-actor">{e.actor || 'system'}</span>
                        {e.target && <><span style={{ color: 'var(--muted)', fontSize: 12 }}>→</span><span style={{ color: 'var(--text-primary)', fontWeight: 500, fontSize: 13 }}>{e.target}</span></>}
                        {ts && <span className="feed-detail" style={{ marginLeft: 'auto' }}>{ts}</span>}
                      </div>
                      {e.detail && <div className="feed-detail">{e.detail}</div>}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ActivityTab;