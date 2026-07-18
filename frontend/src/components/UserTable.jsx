import { useState } from 'react';
import { FiEdit3, FiTrash2, FiMoreVertical } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import ActionsDropdown from './ActionsDropdown';
import { fmtRelative, fmtDate, daysUntil } from '../utils/time';

const UserTable = ({ users, onDelete, onDownload, onEdit, onToggleStatus, onResetUsage, onShowSessions, getSubscriptionLink }) => {
  const { t } = useTranslation();
  const [copyFeedback, setCopyFeedback] = useState({ id: null, status: null });

  const gb = (bytes) => Number(bytes || 0) / 1024 / 1024 / 1024;
  const fmt = (n, digits = 2) => Number(n || 0).toFixed(digits).replace(/\.00$/, '');
  const loginText = (u) => `${Number(u.active_connections || 0)}/${Number(u.max_logins || 0) === 0 ? '∞' : u.max_logins}`;
  const trafficText = (u) => `${fmt(gb(u.used))} / ${u.total ? `${fmt(gb(u.total), 0)} GB` : '∞'}`;
  const statusLabel = user => user.is_active ? (user.online ? 'online' : 'offline') : 'inactive';
  const expClass = (u) => {
    const d = daysUntil(u.expiry_date);
    if (d < 0) return 'exp expired';
    if (d <= 7) return 'exp soon';
    return 'exp ok';
  };
  const expNote = (u) => {
    const d = daysUntil(u.expiry_date);
    if (d < 0) return <small> (expired)</small>;
    if (d <= 7) return <small> ({d}d)</small>;
    return null;
  };

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
            <th>{t('th_expiryDate', 'Expiry')}</th>
            <th>{t('th_totalTraffic', 'Total Traffic')}</th>
            <th>{t('th_maxLogins', 'Max Logins')}</th>
            <th>Last Online</th>
            <th>{t('th_owner', 'Owner')}</th>
            <th className="col-actions">{t('th_actions', 'Actions')}</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.uuid || user.name}>
              <td className="identity-cell">
                <span className="row-avatar">{user.name.slice(0, 2).toUpperCase()}</span>
                <div><strong>{user.name}</strong><small>{user.uuid?.slice(0, 8)}</small></div>
              </td>
              <td><span className={`pill ${statusLabel(user)}`}>{t(statusLabel(user), statusLabel(user).charAt(0).toUpperCase() + statusLabel(user).slice(1))}</span></td>
              <td className={expClass(user)}>{fmtDate(user.expiry_date)}{expNote(user)}</td>
              <td>{trafficText(user)}</td>
              <td><strong className="login-count">{loginText(user)}</strong></td>
              <td className="col-last-online">{fmtRelative(user.last_online)}</td>
              <td>{user.owner}</td>
              <td>
                <div className="row-actions" role="toolbar" aria-label="User actions">
                  <button type="button" title="Edit user" aria-label={`Edit ${user.name}`} onClick={() => onEdit(user)}><FiEdit3 /></button>
                  <button type="button" className="danger" title="Delete user" aria-label={`Delete ${user.name}`} onClick={() => onDelete(user.uuid, user.name)}><FiTrash2 /></button>
                  <ActionsDropdown
                    actions={[
                      { label: 'View sessions', onClick: () => onShowSessions?.(user) },
                      { label: 'Copy subscription link', onClick: () => copySub(user) },
                      { label: 'Download config', onClick: () => onDownload(user) },
                      { label: user.is_active ? 'Deactivate' : 'Activate', onClick: () => onToggleStatus(user) },
                      { label: 'Reset usage', onClick: () => onResetUsage?.(user) },
                    ]}
                  />
                </div>
                {copyFeedback.id === user.uuid && copyFeedback.status === 'copied' && (
                  <span className="copy-ok">Copied ✓</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default UserTable;