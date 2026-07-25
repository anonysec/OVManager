import { FiEdit3, FiRefreshCw, FiTrash2 } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

function usageClass(value) {
  if (value === undefined || value === null) return '';
  if (value <= 50) return 'good';
  if (value <= 80) return 'warn';
  return 'bad';
}

const NodeTableSkeleton = () => {
  return (
    <div className="table-skeleton">
      <div className="skeleton-header">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="sk-line sk-header" style={{ width: i === 0 ? 200 : i <= 2 ? 160 : i === 3 ? 100 : 120 }} />
        ))}
      </div>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="skeleton-row">
          {[...Array(8)].map((_, j) => (
            <div key={j} className="sk-line" style={{ width: j === 0 ? 200 : j <= 2 ? 160 : j === 3 ? 100 : 120 }} />
          ))}
        </div>
      ))}
    </div>
  );
};

const EmptyState = ({ title, detail, iconSvg }) => (
  <div className="empty-state">
    <div className="empty-illustration" aria-hidden="true">
      {iconSvg || (
        <svg viewBox="0 0 120 120" width="120" height="120">
          <circle cx="60" cy="60" r="54" fill="none" stroke="var(--line)" strokeWidth="2" />
          <circle cx="46" cy="50" r="16" fill="none" stroke="var(--orange)" strokeWidth="3" />
          <path d="M24 96c0-14 12-22 26-22s26 8 26 22" fill="none" stroke="var(--orange)" strokeWidth="3" />
          <line x1="78" y1="74" x2="100" y2="96" stroke="var(--orange)" strokeWidth="3" strokeLinecap="round" />
          <circle cx="88" cy="86" r="9" fill="var(--panel)" stroke="var(--orange)" strokeWidth="3" />
        </svg>
      )}
    </div>
    <h3>{title}</h3>
    {detail && <p>{detail}</p>}
  </div>
);

const NodeTable = ({ nodes, isLoading, nodeInfo = {}, onDelete, onCheckStatus, onEdit, onDownloadAll }) => {
  const { t } = useTranslation();
  if (isLoading) return <NodeTableSkeleton />;
  if (!nodes.length) return <EmptyState title={t('noNodes')} detail={t('noNodesBody')} />;

  return (
    <div className="table-container list-table-container">
      <table className="list-table node-list-table">
        <thead>
          <tr>
            <th>{t('th_node')}</th>
            <th>{t('th_address')}</th>
            <th>{t('th_protocol')}</th>
            <th>{t('th_ovpnPort')}</th>
            <th>{t('th_status')}</th>
            <th>{t('th_cpu')}</th>
            <th>{t('th_ram')}</th>
            <th>{t('th_actions')}</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => {
            const info = nodeInfo[node.id] || {};
            return (
              <tr key={node.id}>
                <td style={{ minWidth: 160 }}>
                  <div className="identity-cell">
                    <span className="row-avatar node-avatar">{node.name.slice(0, 2).toUpperCase()}</span>
                    <div><strong style={{ fontSize: 13 }}>{node.name}</strong><small>#{node.id}</small></div>
                  </div>
                </td>
                <td>{node.address}:{node.port}</td>
                <td>{node.protocol}</td>
                <td>{node.ovpn_port}</td>
                <td><span className={node.status ? 'pill online' : 'pill'}>{node.status ? t('active') : t('inactive')}</span></td>
                <td><strong className={usageClass(info.cpu_usage)}>{info.cpu_usage !== undefined ? `${info.cpu_usage}%` : '-'}</strong></td>
                <td><strong className={usageClass(info.memory_usage)}>{info.memory_usage !== undefined ? `${info.memory_usage}%` : '-'}</strong></td>
                <td><div className="row-actions">
                  <button className="icon-btn" title={t('check')} onClick={() => onCheckStatus(node.id)}><FiRefreshCw /></button>
                  <button className="icon-btn" title={t('downloadAll')} onClick={() => onDownloadAll?.(node)}><FiDownloadCloud /></button>
                  <button className="icon-btn" title={t('edit')} onClick={() => onEdit(node)}><FiEdit3 /></button>
                  <button className="icon-btn danger" title={t('delete')} onClick={() => onDelete(node.id, node.name)}><FiTrash2 /></button>
                </div></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default NodeTable;