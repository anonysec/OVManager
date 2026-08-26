import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FiServer, FiCheckCircle, FiXCircle, FiSearch, FiPlus, FiDownload, FiGlobe } from 'react-icons/fi';
import NodeDrawer from '../components/NodeDrawer';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import AddNodeModal from '../components/AddNodeModal';
import EditNodeModal from '../components/EditNodeModal';
import NodeTable from '../components/NodeTable';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import ConfirmModal from '../components/ConfirmModal';

const NodeManagement = () => {
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
  const [density, setDensity] = useState(() => localStorage.getItem('ovmanager-ui-density') === 'compact' ? 'compact' : 'comfortable');
  const { t } = useTranslation();
  const { addToast } = useToast();

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

  useEffect(() => {
    fetchNodes();
  }, [fetchNodes]);

  useEffect(() => {
    if (searchParams.get('add') === '1') {
      setIsAddModalOpen(true);
      searchParams.delete('add');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // Declared above the deep-link effect that calls it: a `const` referenced
  // before its declaration only works because effects run after the body, and
  // it stops updating correctly if the value ever changes.
  const handleOpenEditModal = (node) => {
    setSelectedNode(node);
    setIsEditModalOpen(true);
  };

  // Deep-link: ?node=<id> opens that node's edit modal
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


  useEffect(() => {
    let intervalId;
    const fetchAllNodeStatus = async () => {
      if (!nodes || nodes.length === 0) return;
      const info = {};
      await Promise.all(nodes.map(async (node) => {
        try {
          const res = await apiClient.get(`/nodes/${node.id}/status/`);
          if (res.data.success && res.data.data && res.data.data.node_info && res.data.data.reachable !== false) {
            info[node.id] = res.data.data.node_info;
          }
        } catch { /* ignore */ }
      }));
      setNodeInfo(info);
    };
    fetchAllNodeStatus();
    // Poll node status less aggressively and only when the tab is visible.
    const tick = () => {
      if (document.visibilityState === 'visible') fetchAllNodeStatus();
    };
    intervalId = setInterval(tick, 60000);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(intervalId);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [nodes]);

  const nodeStats = useMemo(() => {
    const activeCount = nodes.filter((node) => node.status).length;
    return {
      total: nodes.length,
      active: activeCount,
      inactive: nodes.length - activeCount,
    };
  }, [nodes]);


  const filteredNodes = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return nodes.filter(node =>
      String(node.name || '').toLowerCase().includes(term)
    );
  }, [nodes, searchTerm]);

  const handleSearchChange = (event) => {
    setSearchTerm(event.target.value);
  };

  const handleDelete = (nodeId, nodeName) => {
    openConfirm(
      t('deleteButton', 'Delete Node'),
      `${t('deleteNodeConfirm', 'Delete node')} "${nodeName}"?`,
      async () => {
        try {
          const response = await apiClient.delete(`/nodes/${nodeId}`);
          if (response.data.success) {
            addToast(response.data.msg || t('nodeDeletedSuccess', 'Node deleted successfully.'), 'success');
          } else {
            addToast(response.data.msg || t('unableToDeleteNode', 'Unable to delete node.'), 'error');
          }
        } catch (error) {
          addToast(error.response?.data?.detail || error.response?.data?.msg || t('errorDeletingNode', 'An error occurred while deleting the node.'), 'error');
        } finally {
          fetchNodes();
        }
      }
    );
  };

  const handleCheckStatus = async (nodeId) => {
    try {
      const response = await apiClient.get(`/nodes/${nodeId}/status/`);
      console.warn(response.data.msg || 'Status check complete.');
      fetchNodes();
    } catch {
      console.warn('Failed to check node status.');
    }
  };

  const handleDownloadAllConfigs = async (node) => {
    // User already clicked 'Download all' — no extra confirmation needed for downloads
    try {
      const response = await apiClient.get(`/nodes/ovpn-all/${node.id}`, {
        responseType: 'blob',
        timeout: 300000,
      });
      const blob = new Blob([response.data], { type: 'application/zip' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `ovpn-configs-${node.name}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.warn(error.response?.data?.detail || 'Failed to download configs.');
    }
  };

  const handleNodeCreated = () => {
    setIsAddModalOpen(false);
    addToast(t('nodeCreatedSuccess', 'Node created successfully.'), 'success');
    fetchNodes();
  };

  const handleExportCsv = () => {
    const esc = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const head = ['id', 'name', 'address', 'port', 'protocol', 'ovpn_port', 'status', 'country', 'cpu', 'memory'];
    const rows = nodes.map((n) => {
      const info = nodeInfo[n.id] || {};
      return [n.id, n.name, n.address, n.port, n.protocol, n.ovpn_port, n.status ? 'active' : 'inactive', n.country_code || '', info.cpu_usage ?? '', info.memory_usage ?? ''];
    });
    const csv = [head, ...rows].map((r) => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `ovmanager-nodes-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };

  const handleToggleNode = async (node) => {
    try {
      await apiClient.put(`/nodes/${node.id}`, {
        name: node.name, address: node.address, tunnel_address: node.tunnel_address || '',
        protocol: node.protocol || 'tcp', ovpn_port: node.ovpn_port, port: node.port,
        status: !node.status, set_new_setting: false, use_tls: node.use_tls || false,
      });
      addToast(node.status ? t('nodeDisabledToast', 'Node disabled.') : t('nodeEnabledToast', 'Node enabled.'), 'success');
      fetchNodes();
    } catch (e) {
      addToast(e.response?.data?.msg || e.response?.data?.detail || t('failedToggleNode', 'Failed to toggle node.'), 'error');
    }
  };

  const applyDensity = (d) => { setDensity(d); localStorage.setItem('ovmanager-ui-density', d); };

  const handleNodeUpdated = (msg) => {
    setIsEditModalOpen(false);
    setSelectedNode(null);
    addToast(msg || t('nodeUpdatedSuccess', 'Node updated successfully.'), 'success');
    fetchNodes();
  };

  return (
    <div id="nodes-view" className="view">
      <div className="view-header">
        <h2>{t('nodes')}</h2>
        <div className="view-header-actions">
          <div className="density-toggle" role="group" aria-label={t('density', 'Density')}>
            <button type="button" className={density === 'comfortable' ? 'active' : ''} onClick={() => applyDensity('comfortable')}>{t('densityComfort', 'Comfort')}</button>
            <button type="button" className={density === 'compact' ? 'active' : ''} onClick={() => applyDensity('compact')}>{t('densityCompact', 'Compact')}</button>
          </div>
          <button type="button" className={`btn btn-secondary btn-sm${grouped ? ' btn-active' : ''}`} onClick={() => { setGrouped(!grouped); localStorage.setItem('ovmanager-ui-node-grouped', grouped ? '0' : '1'); }} title={t('groupByCountry', 'Group by country')}>
            <FiGlobe aria-hidden="true" /> {t('groupByCountry', 'Group')}
          </button>
          <button type="button" onClick={handleExportCsv} className="btn btn-secondary btn-sm export-btn" aria-label={t('exportCsv', 'Export CSV')}>
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
        <div className="search-container">
          <FiSearch className="search-icon" />
          <input
            type="text"
            placeholder={t('searchNodePlaceholder')}
            value={searchTerm}
            onChange={handleSearchChange}
            className="search-input"
          />
        </div>
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
        <ErrorState
          title={t('loadError', 'Could not load nodes')}
          message={t('loadErrorDetail', 'We had trouble reaching the server.')}
          onRetry={fetchNodes}
          retryLabel={t('retry', 'Retry')}
        />
      ) : !isLoading && nodes.length === 0 ? (
        <EmptyState
          title={t('noNodes', 'No nodes configured')}
          description={t('noNodesBody', 'Add your first OVNode to get started.')}
          actionLabel={t('addNewNode', 'Add Node')}
          onAction={() => setIsAddModalOpen(true)}
        />
      ) : (
        <NodeTable
          nodes={filteredNodes}
          isLoading={isLoading}
          nodeInfo={nodeInfo}
          onDelete={handleDelete}
          onCheckStatus={handleCheckStatus}
          onEdit={handleOpenEditModal}
          onDownloadAll={handleDownloadAllConfigs}
          onView={setDrawerNode}
          grouped={grouped}
          density={density}
        />
      )}

      {isAddModalOpen && (
        <AddNodeModal
          isOpen={isAddModalOpen}
          onClose={() => setIsAddModalOpen(false)}
          onNodeCreated={handleNodeCreated}
        />
      )}

      {isEditModalOpen && (
        <EditNodeModal
          isOpen={isEditModalOpen}
          node={selectedNode}
          onClose={() => setIsEditModalOpen(false)}
          onNodeUpdated={handleNodeUpdated}
        />
      )}
      <NodeDrawer
        node={drawerNode}
        onClose={() => setDrawerNode(null)}
        onEdit={(n) => { setDrawerNode(null); handleOpenEditModal(n); }}
        onDelete={(id, name) => { setDrawerNode(null); handleDelete(id, name); }}
        onToggleStatus={handleToggleNode}
        onCheckStatus={handleCheckStatus}
      />
      <ConfirmModal open={confirm.open} onClose={closeConfirm} onConfirm={confirm.onConfirm || (() => {})} title={confirm.title} message={confirm.message} danger={true} confirmLabel={t("deleteButton","Delete")} cancelLabel={t("cancelButton","Cancel")} />

    </div>
  );
};

export default NodeManagement;