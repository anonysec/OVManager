import { FiActivity } from 'react-icons/fi';

const ActivityTab = ({ t, activity }) => {
  return (
    <div className="settings-section">
      <div className="setting-card">
        <div className="setting-card-header"><FiActivity /> Recent Activity</div>
        <div className="setting-card-body">
          {activity.length === 0 ? (
            <div className="empty-state-card"><h3>No activity yet</h3><p>System actions will appear here</p></div>
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
    </div>
  );
};

export default ActivityTab;