import { FiEdit, FiTrash2, FiUser, FiUsers } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

const AdminTable = ({ admins, isLoading, onEdit, onDelete }) => {
  const { t } = useTranslation();
  if (isLoading) return <div className="empty-state">{t('loading', 'Loading...')}</div>;
  if (!admins || admins.length === 0) return <div className="empty-state">{t('noAdminsFound', 'No admins found.')}</div>;

  return (
    <div className="table-container list-table-container">
      <table className="list-table admin-list-table">
        <thead>
          <tr><th>{t('th_admin')}</th><th>{t('th_users_col')}</th><th>{t('th_role')}</th><th>{t('th_actions')}</th></tr>
        </thead>
        <tbody>
          {admins.map((admin) => (
            <tr key={admin.username}>
              <td className="identity-cell"><span className="row-avatar"><FiUser /></span><div><strong>{admin.username}</strong><small>{t('administrator')}</small></div></td>
              <td><FiUsers /> {admin.users_count || 0}</td>
              <td><span className="pill online">{t('adminRole')}</span></td>
              <td><div className="row-actions">
                <button title={t('edit')} onClick={() => onEdit(admin)}><FiEdit /></button>
                <button className="danger" title={t('delete')} onClick={() => onDelete(admin)}><FiTrash2 /></button>
              </div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default AdminTable;
