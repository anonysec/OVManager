import { useTranslation } from 'react-i18next';
import { FiEdit3, FiTrash2 } from 'react-icons/fi';
import PanelSkeleton from './ui/PanelSkeleton';
import EmptyState from './ui/EmptyState';

const AdminTable = ({ admins, isLoading, onEdit, onDelete }) => {
  const { t } = useTranslation();

  if (isLoading) return <PanelSkeleton lines={5} label={t('loading', 'Loading admins…')} />;

  if (!admins.length) {
    return (
      <EmptyState
        title={t('noAdminsFound', 'No admins found')}
        description={t('fillAllFields', 'Add your first admin to get started.')}
      />
    );
  }

  return (
    <div className="list-table-container">
      <table className="list-table">
        <thead>
          <tr>
            <th>{t('th_admin', 'Admin')}</th>
            <th>{t('th_usersCount', 'Users')}</th>
            <th>{t('th_role', 'Bot')}</th>
            <th>{t('th_username', 'Prefix')}</th>
            <th>{t('th_status', 'Status')}</th>
            <th>{t('th_actions', 'Actions')}</th>
          </tr>
        </thead>
        <tbody>
          {admins.map((admin) => (
            <tr key={admin.username}>
              <td><strong>{admin.username}</strong></td>
              <td>{admin.users_count || 0}</td>
              <td>
                {admin.telegram_id ? (
                  <span className="status-pill ok" title={`Telegram ID: ${admin.telegram_id}`}>
                    ✅ {admin.telegram_id}
                  </span>
                ) : (
                  <span className="status-pill" style={{ opacity: 0.5 }}>—</span>
                )}
              </td>
              <td>{admin.username_prefix || <span style={{ opacity: 0.4 }}>—</span>}</td>
              <td><span className="status-pill ok">{t('status_active', 'Active')}</span></td>
              <td className="row-actions">
                <button className="icon-btn" onClick={() => onEdit(admin)} title={t('editButton', 'Edit')} aria-label={`${t('editButton', 'Edit')} ${admin.username}`}>
                  <FiEdit3 />
                </button>
                <button className="icon-btn danger" onClick={() => onDelete(admin)} title={t('deleteButton', 'Delete')} aria-label={`${t('deleteButton', 'Delete')} ${admin.username}`}>
                  <FiTrash2 />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default AdminTable;
