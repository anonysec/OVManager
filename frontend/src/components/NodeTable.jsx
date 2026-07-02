import { FiDownloadCloud, FiEdit3, FiRefreshCw, FiTrash2, FiServer } from 'react-icons/fi';

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
    <div className="node-board">
      {nodes.map((node) => {
        const info = nodeInfo[node.id] || {};
        return (
          <article className="node-card" key={node.id}>
            <div className="node-top">
              <div className="node-symbol"><FiServer /></div>
              <div>
                <h3>{node.name}</h3>
                <p>{node.address}:{node.port}</p>
              </div>
              <span className={node.status ? 'pill online' : 'pill'}>{node.status ? 'Active' : 'Inactive'}</span>
            </div>

            <div className="node-specs">
              <div><span>Protocol</span><strong>{node.protocol}</strong></div>
              <div><span>OVPN Port</span><strong>{node.ovpn_port}</strong></div>
              <div><span>CPU</span><strong className={usageClass(info.cpu_usage)}>{info.cpu_usage !== undefined ? `${info.cpu_usage}%` : '-'}</strong></div>
              <div><span>RAM</span><strong className={usageClass(info.memory_usage)}>{info.memory_usage !== undefined ? `${info.memory_usage}%` : '-'}</strong></div>
            </div>

            <div className="card-actions-row node-actions">
              <button onClick={() => onCheckStatus(node.id)}><FiRefreshCw /> Check</button>
              <button onClick={() => onDownloadAll?.(node)}><FiDownloadCloud /> All configs</button>
              <button onClick={() => onEdit(node)}><FiEdit3 /> Edit</button>
              <button className="danger" onClick={() => onDelete(node.id, node.name)}><FiTrash2 /> Delete</button>
            </div>
          </article>
        );
      })}
    </div>
  );
};

export default NodeTable;
