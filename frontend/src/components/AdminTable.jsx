import { FiEdit3, FiTrash2 } from 'react-icons/fi';

const AdminTableSkeleton = () => {
  return (
    <div className="table-skeleton">
      <div className="skeleton-header">
        {[...Array(6)].map((_, i) => <div key={i} className="sk-line sk-header" style={{ width: i === 0 ? 200 : i <= 2 ? 120 : 100 }} />)}
      </div>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="skeleton-row">
          {[...Array(6)].map((_, j) => <div key={j} className="sk-line" style={{ width: j === 0 ? 200 : 120 }} />)}
        </div>
      ))}
    </div>
  );
};

const EmptyState = ({ title, detail }) => {
  return (
    <div className="empty-state">
      <div className="empty-illustration" aria-hidden="true">
        <svg viewBox="0 0 120 120" width="120" height="120">
          <circle cx="60" cy="60" r="54" fill="none" stroke="var(--line)" strokeWidth="2" />
          <circle cx="46" cy="50" r="16" fill="none" stroke="var(--orange)" strokeWidth="3" />
          <path d="M24 96c0-14 12-22 26-22s26 8 26 22" fill="none" stroke="var(--orange)" strokeWidth="3" />
          <line x1="78" y1="74" x2="100" y2="96" stroke="var(--orange)" strokeWidth="3" strokeLinecap="round" />
          <circle cx="88" cy="86" r="9" fill="var(--panel)" stroke="var(--orange)" strokeWidth="3" />
        </svg>
      </div>
      <h3>{title}</h3>
      {detail && <p>{detail}</p>}
    </div>
  );
};

const AdminTable = ({ admins, isLoading, onEdit, onDelete }) => {
  if (isLoading) return <AdminTableSkeleton />;

  if (!admins.length) {
    return (
      <EmptyState title="No admins found" detail="There are no admins configured yet. Add your first admin to get started." />
    );
  }

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