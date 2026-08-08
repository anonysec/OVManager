import { FiEdit3, FiRefreshCw, FiTrash2, FiDownloadCloud } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import EmptyState from './ui/EmptyState';
import StatusBadge from './ui/StatusBadge';
import { usePrivacyMask, PrivacyEye } from './ui';

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



const NodeTable = ({ nodes, isLoading, nodeInfo = {}, onDelete, onCheckStatus, onEdit, onDownloadAll }) => {
  const { t } = useTranslation();
  const maskIps = usePrivacyMask();

  // Mask IP address but keep node name/port visible for usability
  const maskAddress = (addr) => {
    if (!maskIps || !addr) return addr;
    const ipv4 = addr.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (ipv4) {
      return `${ipv4[1]}.*.*.${ipv4[4]}`;
    }
    const ipv6Match = addr.match(/^([0-9a-f:]{1,5})/i);
    if (ipv6Match) {
      return `${ipv6Match[1]}::...`;
    }
    return addr;
  };

  if (isLoading) return <NodeTableSkeleton />;
  if (!nodes.length) return <EmptyState title={t('noNodes')} description={t('noNodesBody')} />;

  return (
    <div className="table-container list-table-container">
      <table className="list-table node-list-table">
        <thead>
          <tr>
            <th>{t('th_node')}</th>
            <th>
              <span className="th-with-eye">
                {t('th_address')}
                <PrivacyEye className="th-privacy-eye" size={14} />
              </span>
            </th>
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
                <td className="node-name-cell">
                  <div className="identity-cell">
                    <span className="row-avatar node-avatar">{node.name.slice(0, 2).toUpperCase()}</span>
                    <div><strong className="node-name-text">{node.name}</strong><small>#{node.id}</small></div>
                  </div>
                </td>
                <td><span className="node-address">{maskAddress(node.address)}:{node.port}</span></td>
                <td>{node.protocol}</td>
                <td>{node.ovpn_port}</td>
                <td><StatusBadge status={node.status ? 'online' : 'offline'} label={node.status ? t('active') : t('inactive')} /></td>
                <td><strong className={usageClass(info.cpu_usage)}>{info.cpu_usage !== undefined ? `${info.cpu_usage}%` : '-'}</strong></td>
                <td><strong className={usageClass(info.memory_usage)}>{info.memory_usage !== undefined ? `${info.memory_usage}%` : '-'}</strong></td>
                <td><div className="row-actions">
                  <button className="icon-btn" title={t('check')} aria-label={`${t('check')} ${node.name}`} onClick={() => onCheckStatus(node.id)}><FiRefreshCw /></button>
                  <button className="icon-btn" title={t('downloadAll')} aria-label={`${t('downloadAll')} ${node.name}`} onClick={() => onDownloadAll?.(node)}><FiDownloadCloud /></button>
                  <button className="icon-btn" title={t('edit')} aria-label={`${t('edit')} ${node.name}`} onClick={() => onEdit(node)}><FiEdit3 /></button>
                  <button className="icon-btn danger" title={t('delete')} aria-label={`${t('delete')} ${node.name}`} onClick={() => onDelete(node.id, node.name)}><FiTrash2 /></button>
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