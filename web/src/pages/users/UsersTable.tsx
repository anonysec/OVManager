import { daysUntil, fmtDate } from '../../utils/time';
import { formatBytes } from '../../utils/format';
import { FiEdit2, FiTrash2, FiKey, FiGlobe, FiClock } from 'react-icons/fi';

export default function UsersTable({ users, keepOneUser, onEdit, onDelete, onExtend, onSub, onDownload, t }: any) {
  return (
    <table className="dt-table">
      <thead><tr><th>{t('userName', 'Name')}</th><th>{t('userStatus', 'Status')}</th><th>{t('colUsage', 'Usage')}</th><th>{t('colExpiry', 'Expiry')}</th><th>{t('actions', 'Actions')}</th></tr></thead>
      <tbody>
        {users.map((u: any) => {
          const total = u.total != null ? Number(u.total) : null;
          const used = Number(u.used || 0);
          const pct = total && total > 0 ? Math.min(100, (used / total) * 100) : null;
          const dLeft = daysUntil(u.expiry_date);
          const expiringSoon = dLeft != null && dLeft <= 7 && dLeft >= 0;
          return (
            <tr key={u.id || u.uuid} data-testid={`user-row-${u.name}`}>
              <td><span className="dt-cell-main">{u.name}</span><span className="dt-cell-sub um-cell-id">#{u.id}</span></td>
              <td>{u.is_active ? <span className="dt-status dt-status--active">{t('active', 'Active')}</span> : <span className="dt-status dt-status--inactive">{t('inactive', 'Inactive')}</span>}</td>
              <td><span className="dt-usage">{formatBytes(used)} / {total != null ? formatBytes(total) : '∞'}</span>{pct != null && <span className="dt-usage-bar"><i style={{ width: `${pct}%` }} /></span>}</td>
              <td><span className={expiringSoon ? 'dt-expiry-soon' : ''}>{fmtDate(u.expiry_date)}</span>{dLeft != null && <span className="dt-cell-sub">{dLeft < 0 ? t('expired', 'Expired') : t('inDays', 'in {{n}}d', { n: dLeft })}</span>}</td>
              <td className="dt-actions">
                <button type="button" className="dt-icon-btn" title={t('rowEdit', 'Edit')} aria-label={`${t('rowEdit', 'Edit')} ${u.name}`} onClick={() => onEdit(u)}><FiEdit2 size={15} /></button>
                <button type="button" className="dt-icon-btn is-danger" title={keepOneUser ? t('keepOneUser', 'You must keep at least one user') : t('rowDelete', 'Delete')} aria-label={`${t('rowDelete', 'Delete')} ${u.name}`} disabled={keepOneUser} onClick={() => onDelete(u)}><FiTrash2 size={15} /></button>
                <button type="button" className="dt-icon-btn" title={t('extend', 'Extend')} aria-label={`${t('extend', 'Extend')} ${u.name}`} onClick={() => onExtend(u)}><FiClock size={15} /></button>
                <button type="button" className="dt-icon-btn" title={t('subscriptionLink', 'Subscription')} aria-label={`${t('subscriptionLink', 'Subscription')} ${u.name}`} onClick={() => onSub(u)}><FiKey size={15} /></button>
                <button type="button" className="dt-icon-btn" title={t('downloadOvpn', 'Download .ovpn')} aria-label={`${t('downloadOvpn', 'Download .ovpn')} ${u.name}`} onClick={() => onDownload(u)}><FiGlobe size={15} /></button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
