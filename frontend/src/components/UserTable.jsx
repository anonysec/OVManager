import { useState } from 'react';
import { FiCopy, FiDownload, FiEdit3, FiPower, FiRefreshCw, FiTrash2, FiActivity } from 'react-icons/fi';

const UserTable = ({ users, onDelete, onDownload, onEdit, onToggleStatus, onResetUsage, onShowSessions, getSubscriptionLink }) => {
  const [copyFeedback, setCopyFeedback] = useState({ id: null, status: null });

  const gb = (bytes) => {
    if (bytes === null || bytes === undefined) return 0;
    const value = Number(bytes) / 1024 / 1024 / 1024;
    return Number.isFinite(value) ? value : 0;
  };

  const trafficText = (user) => {
    const used = gb(user.used);
    if (user.total === null || user.total === undefined) return `${used.toFixed(2)} / ∞ GB`;
    return `${used.toFixed(2)} / ${gb(user.total).toFixed(0)} GB`;
  };

  const trafficPercent = (user) => {
    if (!user.total) return 0;
    return Math.min(100, Math.max(0, (Number(user.used || 0) / Number(user.total)) * 100));
  };

  const loginText = (user) => {
    const active = Number(user.active_connections || 0);
    const max = Number(user.max_logins || 0);
    return `${active}/${max === 0 ? '∞' : max}`;
  };

  const showCopyFeedback = (user, status) => {
    const id = user?.uuid || user?.name;
    setCopyFeedback({ id, status });
    window.setTimeout(() => {
      setCopyFeedback((current) => (current.id === id ? { id: null, status: null } : current));
    }, 1400);
  };

  const copyLabel = (user) => {
    const id = user?.uuid || user?.name;
    if (copyFeedback.id !== id) return 'Copy sub';
    if (copyFeedback.status === 'copied') return 'Copied';
    return 'No link';
  };

  const copySub = async (user) => {
    const link = getSubscriptionLink?.(user) || '';
    if (!link) return showCopyFeedback(user, 'empty');
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(link);
      } else {
        const ta = document.createElement('textarea');
        ta.value = link;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      showCopyFeedback(user, 'copied');
    } catch {
      showCopyFeedback(user, 'empty');
    }
  };

  if (!users.length) {
    return <div className="empty-state">No users found.</div>;
  }

  return (
    <div className="user-board">
      {users.map((user) => {
        const percent = trafficPercent(user);
        return (
          <article className={`user-card ${user.online ? 'is-online' : ''}`} key={user.uuid || user.name}>
            <div className="user-card-head">
              <div className="user-avatar">{user.name.slice(0, 2).toUpperCase()}</div>
              <div className="user-title">
                <h3>{user.name}</h3>
                <span className={user.online ? 'pill online' : 'pill'}>{user.online ? 'Online' : 'Offline'}</span>
              </div>
              <div className="login-counter">{loginText(user)}</div>
            </div>

            <div className="user-card-grid">
              <div>
                <span>Expiry</span>
                <strong>{new Date(user.expiry_date).toLocaleDateString('en-CA')}</strong>
              </div>
              <div>
                <span>Owner</span>
                <strong>{user.owner}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{user.is_active ? 'Active' : 'Inactive'}</strong>
              </div>
            </div>

            <div className="traffic-block">
              <div className="traffic-row">
                <span>Total Traffic</span>
                <strong>{trafficText(user)}</strong>
              </div>
              <div className="progress-track"><div style={{ width: `${percent}%` }} /></div>
            </div>

            <div className="card-actions-row">
              <button onClick={() => onShowSessions?.(user)}><FiActivity /> Sessions</button>
              <button onClick={() => copySub(user)}><FiCopy /> {copyLabel(user)}</button>
              <button onClick={() => onDownload(user)}><FiDownload /> Config</button>
              <button onClick={() => onEdit(user)}><FiEdit3 /> Edit</button>
              <button onClick={() => onResetUsage?.(user)}><FiRefreshCw /> Reset</button>
              <button onClick={() => onToggleStatus(user)}><FiPower /> {user.is_active ? 'Disable' : 'Enable'}</button>
              <button className="danger" onClick={() => onDelete(user.uuid, user.name)}><FiTrash2 /> Delete</button>
            </div>
          </article>
        );
      })}
    </div>
  );
};

export default UserTable;
