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
                <div className="row-actions" role="toolbar" aria-label="User actions">
                  <button type="button" title="View sessions" aria-label={`View sessions for ${user.name}`} onClick={() => onShowSessions?.(user)}><FiActivity /></button>
                  <button type="button" title="Copy subscription link" aria-label={`Copy subscription link for ${user.name}`} onClick={() => copySub(user)}><FiCopy />{copyFeedback.id === user.uuid ? '✓' : ''}</button>
                  <button type="button" title="Download OpenVPN config" aria-label={`Download OpenVPN config for ${user.name}`} onClick={() => onDownload(user)}><FiDownload /></button>
                  <button type="button" title="Edit user" aria-label={`Edit ${user.name}`} onClick={() => onEdit(user)}><FiEdit3 /></button>
                  <button type="button" title="Reset usage" aria-label={`Reset usage for ${user.name}`} onClick={() => onResetUsage?.(user)}><FiRefreshCw /></button>
                  <button type="button" title="Toggle user status" aria-label={user.is_active ? `Deactivate ${user.name}` : `Activate ${user.name}`} onClick={() => onToggleStatus(user)}><FiPower /></button>
                  <button type="button" className="danger" title="Delete user" aria-label={`Delete ${user.name}`} onClick={() => onDelete(user.uuid, user.name)}><FiTrash2 /></button>
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
