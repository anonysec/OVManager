import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FiServer, FiCheckCircle, FiXCircle, FiSearch, FiPlus, FiDownload, FiGlobe } from 'react-icons/fi';
import NodeDrawer from '../components/NodeDrawer';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import AddNodeModal from '../components/AddNodeModal';
import EditNodeModal from '../components/EditNodeModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import ConfirmModal from '../components/ConfirmModal';

const NodeManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [nodes, setNodes] = useState([]);
  const [nodeInfo, setNodeInfo] = useState({});
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const openConfirm = (title, message, onConfirm) => setConfirm({ open: true, title, message, onConfirm });
  const closeConfirm = () => setConfirm(c => ({ ...c, open: false }));
  const [loadError, setLoadError] = useState(false);
  const [drawerNode, setDrawerNode] = useState(null);
  const [grouped, setGrouped] = useState(() => localStorage.getItem('ovmanager-ui-node-grouped') === '1');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchNodes = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const response = await apiClient.get('/nodes/');
      if (response.data.success) {
        setNodes(asList(response.data, 'nodes'));
      }
    } catch (error) {
      console.error('Error fetching nodes:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { fetchNodes(); }, [fetchNodes]);

  useEffect(() => {
    if (searchParams.get('add') === '1') {
      setIsAddModalOpen(true);
      searchParams.delete('add');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // Live: poll node status while page is open (no list to render into, but
  // a future table will want it).
  useEffect(() => {
    if (!nodes || nodes.length === 0) return undefined;
    const fetchAllNodeStatus = async () => {
      const info = { ...nodeInfo };
      await Promise.all(nodes.map(async (node) => {
        try {
          const res = await apiClient.get(`/nodes/${node.id}/status/`);
          if (res.data.success && res.data.node_info) {
            info[node.id] = res.data.node_info;
          }
        } catch { /* keep previous */ }
      }));
      setNodeInfo(info);
    };
    fetchAllNodeStatus();
    const intervalId = setInterval(fetchAllNodeStatus, 30000);
    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes]);

  // ── Derived stats ─────────────────────────────────────────────────────
  const nodeStats = useMemo(() => ({
    total: nodes.length,
    active: nodes.filter(n => n.status).length,
    inactive: nodes.filter(n => !n.status).length,
  }), [nodes]);

  const filteredNodes = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return nodes.filter(n => !term || n.name.toLowerCase().includes(term));
  }, [nodes, searchTerm]);

  // ── Handlers ──────────────────────────────────────────────────────────
  const handleOpenEditModal = (node) => {
    setSelectedNode(node);
    setIsEditModalOpen(true);
  };

  useEffect(() => {
    const nodeId = searchParams.get('node');
    if (!nodeId) return;
    const n = nodes.find((x) => String(x.id) === String(nodeId));
    if (n) {
      handleOpenEditModal(n);
      searchParams.delete('node');
      setSearchParams(searchParams, { replace: true });
    }
  }, [nodes, searchParams, setSearchParams]);

  const handleDelete = (node) => {
    openConfirm(
      t('deleteNode'),
      t('confirmDeleteNode', 'Delete {{name}}? This cannot be undone.', { name: node.name }),
      async () => {
        try {
          const res = await apiClient.delete(`/nodes/${node.id}/`);
          addToast(res.data?.success ? t('deleted') : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          fetchNodes();
        } catch { addToast(t('error'), 'error'); }
      }
    );
  };

  const handleCheckStatus = async (nodeId) => {
    try {
      const response = await apiClient.get(`/nodes/${nodeId}/status/`);
      addToast(response.data.msg || t('statusCheckDone', 'Status check complete.'), 'success');
      fetchNodes();
    } catch (e) {
      addToast(e.response?.data?.detail || t('statusCheckFailed', 'Failed to check node status.'), 'error');
    }
  };

  const handleDownloadAllConfigs = async (node) => {
    try {
      const response = await apiClient.get(`/nodes/ovpn-all/${node.id}`, { responseType: 'blob', timeout: 300000 });
      const blob = new Blob([response.data], { type: 'application/zip' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `ovpn-configs-${node.name}.zip`;
      document.body.appendChild(link); link.click(); link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      addToast(e.response?.data?.detail || t('exportFailed'), 'error');
    }
  };

  const handleNodeCreated = () => {
    setIsAddModalOpen(false);
    addToast(t('nodeCreatedSuccess'), 'success');
    fetchNodes();
  };

  const handleExportCsv = () => {
      const esc = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const head = ['id', 'name', 'address', 'port', 'protocol', 'ovpn_port', 'status', 'country'];
    const rows = nodes.map(n => [n.id, n.name, n.address, n.port, n.protocol, n.ovpn_port, n.status ? 'active' : 'inactive', n.country_code || '']);
    const csv = [head, ...rows].map(r => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `ovmanager-nodes-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    addToast(t('exported'), 'success');
  };

  const handleSearchChange = (e) => setSearchTerm(e.target.value);

  const handleNodeUpdated = (msg) => {
    setIsEditModalOpen(false);
    setSelectedNode(null);
    addToast(msg || t('nodeUpdatedSuccess'), 'success');
    fetchNodes();
  };

  return (
    <div id="nodes-view" className="view">
      <div className="view-header">
        <h2>{t('nodes')}</h2>
        <div className="view-header-actions">
          <button type="button" className={`btn btn-secondary btn-sm${grouped ? ' btn-active' : ''}`} onClick={() => { setGrouped(!grouped); localStorage.setItem('ovmanager-ui-node-grouped', grouped ? '0' : '1'); }} title={t('groupByCountry')}>
            <FiGlobe aria-hidden="true" /> {t('groupByCountry', 'Group')}
          </button>
          <button type="button" onClick={handleExportCsv} className="btn btn-secondary btn-sm" aria-label={t('exportCsv')}>
            <FiDownload aria-hidden="true" /> {t('exportCsv', 'CSV')}
          </button>
          <button type="button" onClick={() => setIsAddModalOpen(true)} className="btn">
            <FiPlus aria-hidden="true" />
            <span>{t('addNewNode')}</span>
          </button>
        </div>
      </div>

      <div className="user-stats-row">
        <div className="user-stat" style={{ '--us-accent': '#90caf9' }}>
          <span className="us-ico"><FiServer /></span>
          <span className="us-body">
            <span className="us-label">{t('nodesTotal')}</span>
            <span className="us-value">{nodeStats.total}</span>
          </span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#43a047' }}>
          <span className="us-ico"><FiCheckCircle /></span>
          <span className="us-body">
            <span className="us-label">{t('nodesActive')}</span>
            <span className="us-value">{nodeStats.active}</span>
          </span>
        </div>
        <div className="user-stat" style={{ '--us-accent': '#e53935' }}>
          <span className="us-ico"><FiXCircle /></span>
          <span className="us-body">
            <span className="us-label">{t('nodesInactive')}</span>
            <span className="us-value">{nodeStats.inactive}</span>
          </span>
        </div>
      </div>

      <div className="search-pagination-controls">
        <label className="search-field" style={{ flex: 1, maxWidth: 280 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input
            type="search"
            placeholder={t('searchNodePlaceholder', 'Search by name…')}
            value={searchTerm}
            onChange={handleSearchChange}
            className="search-input"
            aria-label={t('searchNodePlaceholder', 'Search by name…')}
          />
        </label>
        <div className="results-meta" aria-live="polite">
          <strong>{filteredNodes.length}</strong> {t('results', 'results')}
          {searchTerm && (
            <button type="button" className="toolbar-clear" onClick={() => setSearchTerm('')}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

      {loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={fetchNodes} retryLabel={t('retry')} />
      ) : !isLoading && nodes.length === 0 ? (
        <EmptyState title={t('noNodes')} description={t('noNodesBody')} actionLabel={t('addNewNode')} onAction={() => setIsAddModalOpen(true)} />
      ) : (
        <div className="placeholder-list">
          <p className="placeholder-notice">{t('listRemoved', 'Table removed — UI will be redesigned. Current nodes: {count}', { count: filteredNodes.length })}</p>
        </div>
      )}

      {isAddModalOpen && (
        <AddNodeModal isOpen={isAddModalOpen} onClose={() => setIsAddModalOpen(false)} onNodeCreated={handleNodeCreated} />
      )}
      {isEditModalOpen && selectedNode && (
        <EditNodeModal isOpen={isEditModalOpen} node={selectedNode} onClose={() => { setIsEditModalOpen(false); setSelectedNode(null); }} onNodeUpdated={handleNodeUpdated} />
      )}
      {drawerNode && (
        <NodeDrawer
          node={drawerNode}
          onClose={() => setDrawerNode(null)}
          onEdit={(n) => { setDrawerNode(null); handleOpenEditModal(n); }}
          onDelete={(n) => { setDrawerNode(null); handleDelete(n); }}
          onCheckStatus={handleCheckStatus}
          onDownloadAll={handleDownloadAllConfigs}
        />
      )}

      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm}
        title={confirm.title}
        message={confirm.message}
      />
    </div>
  );
};

export default NodeManagement;