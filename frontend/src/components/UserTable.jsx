import { useState } from 'react';
import { FiActivity, FiCopy, FiDownload, FiEdit3, FiPower, FiRefreshCw, FiTrash2 } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

const UserTable = ({ users, onDelete, onDownload, onEdit, onToggleStatus, onResetUsage, onShowSessions, getSubscriptionLink }) => {
  const { t } = useTranslation();
  const [copyFeedback, setCopyFeedback] = useState({ id: null, status: null });

  const gb = (bytes) => Number(bytes || 0) / 1024 / 1024 / 1024;
  const fmt = (n, digits = 2) => Number(n || 0).toFixed(digits).replace(/\.00$/, '');
  const loginText = (u) => `${Number(u.active_connections || 0)}/${Number(u.max_logins || 0) === 0 ? '∞' : u.max_logins}`;
  const trafficText = (u) => `${fmt(gb(u.used))} / ${u.total ? `${fmt(gb(u.total), 0)} GB` : '∞'}`;

  const copySub = async (user) => {
    const link = getSubscriptionLink?.(user) || '';
    if (!link) return setCopyFeedback({ id: user.uuid, status: 'empty' });
    try {
      await navigator.clipboard?.writeText(link);
      setCopyFeedback({ id: user.uuid, status: 'copied' });
    } catch {
      const ta = document.createElement('textarea');
      ta.value = link;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      setCopyFeedback({ id: user.uuid, status: 'copied' });
    }
    setTimeout(() => setCopyFeedback({ id: null, status: null }), 1400);
  };

  if (!users.length) return <div className="empty-state">{t('noUsersFound', 'No users found.')}</div>;

  return (
    <div className="table-container list-table-container">
      <table className="list-table user-list-table">
        <thead>
          <tr>
            <th>{t('th_username', 'Username')}</th>
            <th>{t('status', 'Status')}</th>
            <th>{t('th_expiryDate', 'Expiry Date')}</th>
            <th>{t('th_totalTraffic', 'Total Traffic')}</th>
            <th>{t('th_maxLogins', 'Max Logins')}</th>
            <th>{t('th_owner', 'Owner')}</th>
            <th>{t('th_actions', 'Actions')}</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.uuid || user.name}>
              <td className="identity-cell">
                <span className="row-avatar">{user.name.slice(0, 2).toUpperCase()}</span>
                <div><strong>{user.name}</strong><small>{user.uuid?.slice(0, 8)}</small></div>
              </td>
              <td><span className={user.online ? 'pill online' : 'pill'}>{user.online ? t('online', 'Online') : t('offline', 'Offline')}</span></td>
              <td>{new Date(user.expiry_date).toLocaleDateString('en-CA')}</td>
              <td>{trafficText(user)}</td>
              <td><strong className="login-count">{loginText(user)}</strong></td>
              <td>{user.owner}</td>
              <td>
                <div className="row-actions">
                  <button title="Sessions" onClick={() => onShowSessions?.(user)}><FiActivity /></button>
                  <button title="Copy subscription" onClick={() => copySub(user)}><FiCopy />{copyFeedback.id === user.uuid ? '✓' : ''}</button>
                  <button title="Download config" onClick={() => onDownload(user)}><FiDownload /></button>
                  <button title="Edit" onClick={() => onEdit(user)}><FiEdit3 /></button>
                  <button title="Reset usage" onClick={() => onResetUsage?.(user)}><FiRefreshCw /></button>
                  <button title="Toggle status" onClick={() => onToggleStatus(user)}><FiPower /></button>
                  <button className="danger" title="Delete" onClick={() => onDelete(user.uuid, user.name)}><FiTrash2 /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default UserTable;
