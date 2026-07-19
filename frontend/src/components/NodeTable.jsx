import { FiDownloadCloud, FiEdit3, FiRefreshCw, FiTrash2 } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

function usageClass(value) {
  if (value === undefined || value === null) return '';
  if (value <= 50) return 'good';
  if (value <= 80) return 'warn';
  return 'bad';
}

const NodeTable = ({ nodes, isLoading, nodeInfo = {}, onDelete, onCheckStatus, onEdit, onDownloadAll }) => {
  const { t } = useTranslation();
  if (isLoading) return <div className="empty-state">{t('loadingNodes')}</div>;
  if (!nodes.length) return <div className="empty-state">{t('noNodes')}</div>;

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
                <td className="identity-cell"><span className="row-avatar node-avatar">{node.name.slice(0, 2).toUpperCase()}</span><div><strong>{node.name}</strong><small>#{node.id}</small></div></td>
                <td>{node.address}:{node.port}</td>
                <td>{node.protocol}</td>
                <td>{node.ovpn_port}</td>
                <td><span className={node.status ? 'pill online' : 'pill'}>{node.status ? t('active') : t('inactive')}</span></td>
                <td><strong className={usageClass(info.cpu_usage)}>{info.cpu_usage !== undefined ? `${info.cpu_usage}%` : '-'}</strong></td>
                <td><strong className={usageClass(info.memory_usage)}>{info.memory_usage !== undefined ? `${info.memory_usage}%` : '-'}</strong></td>
                <td><div className="row-actions">
                  <button title={t('check')} onClick={() => onCheckStatus(node.id)}><FiRefreshCw /></button>
                  <button title={t('downloadAll')} onClick={() => onDownloadAll?.(node)}><FiDownloadCloud /></button>
                  <button title={t('edit')} onClick={() => onEdit(node)}><FiEdit3 /></button>
                  <button className="danger" title={t('delete')} onClick={() => onDelete(node.id, node.name)}><FiTrash2 /></button>
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
