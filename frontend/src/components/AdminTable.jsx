import { FiTrash2, FiEdit3 } from 'react-icons/fi';

const AdminTable = ({ admins, isLoading, onEdit, onDelete }) => {
  if (isLoading) return <div className="table-skeleton">Loading admins…</div>;

  return (
    <div className="list-table-container">
      <table className="list-table">
        <thead>
          <tr>
            <th>{'Admin'}</th>
            <th>{'Users'}</th>
            <th>{'Bot'}</th>
            <th>{'Prefix'}</th>
            <th>{'Status'}</th>
            <th>{'Actions'}</th>
          </tr>
        </thead>
        <tbody>
          {admins.map((admin) => (
            <tr key={admin.username}>
              <td><strong>{admin.username}</strong></td>
              <td>{admin.users_count || 0}</td>
              <td>
                {admin.telegram_id ? (
                  <span className="status-pill ok" title={`Telegram ID: ${admin.telegram_id}`}>✅ {admin.telegram_id}</span>
                ) : (
                  <span className="status-pill" style={{ opacity: 0.5 }}>❌</span>
                )}
              </td>
              <td>{admin.username_prefix || <span style={{ opacity: 0.4 }}>—</span>}</td>
              <td><span className="status-pill ok">Active</span></td>
              <td className="row-actions">
                <button className="icon-btn" onClick={() => onEdit(admin)} title="Edit"><FiEdit3 /></button>
                <button className="icon-btn danger" onClick={() => onDelete(admin)} title="Delete"><FiTrash2 /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default AdminTable;