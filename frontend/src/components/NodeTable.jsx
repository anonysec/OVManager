import { FiDownloadCloud, FiEdit3, FiRefreshCw, FiTrash2 } from 'react-icons/fi';

function usageClass(value) {
  if (value === undefined || value === null) return '';
  if (value <= 50) return 'good';
  if (value <= 80) return 'warn';
  return 'bad';
}

const NodeTable = ({ nodes, isLoading, nodeInfo = {}, onDelete, onCheckStatus, onEdit, onDownloadAll }) => {
  if (isLoading) return <div className="empty-state">Loading nodes...</div>;
  if (!nodes.length) return <div className="empty-state">No nodes found.</div>;

  return (
    <div className="table-container list-table-container">
      <table className="list-table node-list-table">
        <thead>
          <tr>
            <th>Node</th>
            <th>Address</th>
            <th>Protocol</th>
            <th>OVPN Port</th>
            <th>Status</th>
            <th>CPU</th>
            <th>RAM</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => {
            const info = nodeInfo[node.id] || {};
            return (
              <tr key={node.id}>
                <td className="identity-cell"><span className="row-avatar node-avatar">{node.name.slice(0, 2).toUpperCase()}</span><div><strong>{node.name}</strong><small>ID #{node.id}</small></div></td>
                <td>{node.address}:{node.port}</td>
                <td>{node.protocol}</td>
                <td>{node.ovpn_port}</td>
                <td><span className={node.status ? 'pill online' : 'pill'}>{node.status ? 'Active' : 'Inactive'}</span></td>
                <td><strong className={usageClass(info.cpu_usage)}>{info.cpu_usage !== undefined ? `${info.cpu_usage}%` : '-'}</strong></td>
                <td><strong className={usageClass(info.memory_usage)}>{info.memory_usage !== undefined ? `${info.memory_usage}%` : '-'}</strong></td>
                <td><div className="row-actions">
                  <button title="Check" onClick={() => onCheckStatus(node.id)}><FiRefreshCw /></button>
                  <button title="Download all configs" onClick={() => onDownloadAll?.(node)}><FiDownloadCloud /></button>
                  <button title="Edit" onClick={() => onEdit(node)}><FiEdit3 /></button>
                  <button className="danger" title="Delete" onClick={() => onDelete(node.id, node.name)}><FiTrash2 /></button>
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
