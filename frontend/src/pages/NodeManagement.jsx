import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  FiCheckCircle, FiDownload, FiEdit2, FiFileText, FiPlus, FiPower,
  FiRefreshCw, FiSearch, FiServer, FiTrash2, FiUsers, FiXCircle,
} from 'react-icons/fi';
import NodeDrawer from '../components/NodeDrawer';
import NodeFormModal from '../components/NodeFormModal';
import ConfirmModal from '../components/ConfirmModal';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { readPrefs } from '../utils/notifPrefs';
import { nodeMeta } from '../utils/geo';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, StatCard, StatusBadge,
} from '../components/ui';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import './NodeManagement.css';

/**
 * Nodes page — one row per OVNode with live status, version/TLS chips and
 * quick actions. The heavy lifting (DNS/IPv6/ports, restart, update, logs)
 * lives in NodeDrawer; the list stays scannable.
 */

const tlsMeta = (mode, t) => {
  if (mode === 'verified') return { tone: 'success', label: t('tlsVerified', 'Verified') };
  if (mode === 'plain') return { tone: 'danger', label: t('tlsPlain', 'Plain HTTP') };
  if (mode === 'unverified' || mode === 'self-signed') return { tone: 'warning', label: t('tlsSelfSigned', 'Self-signed') };
  return null;
};

const NodeManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [nodes, setNodes] = useState([]);
  const [nodeInfo, setNodeInfo] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [busy, setBusy] = useState({});
  const [drawer, setDrawer] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [editNode, setEditNode] = useState(null);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });

  const openConfirm = (title, message, onConfirm) => setConfirm({ open: true, title, message, onConfirm });
  const closeConfirm = () => setConfirm((c) => ({ ...c, open: false }));

  const markBusy = (key, value) => setBusy((prev) => {
    const next = { ...prev };
    if (value) next[key] = true;
    else delete next[key];
    return next;
  });

  const fetchNodes = useCallback(async ({ background = false } = {}) => {
    if (!background) setIsLoading(true);
    setLoadError(false);
    try {
      const response = await apiClient.get('/nodes/');
      if (response.data?.success) setNodes(asList(response.data, 'nodes'));
      else setLoadError(true);
    } catch {
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const { subscribe } = useLive();
  useEffect(() => {
    const unsubscribe = subscribe('nodes.changed', () => fetchNodes({ background: true }));
    return () => unsubscribe();
  }, [subscribe, fetchNodes]);

  useEffect(() => { fetchNodes(); }, [fetchNodes]);

  // Poll every node's live status. Re-armed whenever the node list changes so
  // the refresh interval always covers the current set.
  useEffect(() => {
    if (nodes.length === 0) return undefined;
    let cancelled = false;
    const fetchAllStatus = async () => {
      const fresh = {};
      await Promise.all(nodes.map(async (node) => {
        try {
          const res = await apiClient.get(`/nodes/${node.id}/status/`);
          if (res.data?.success && res.data?.data) fresh[node.id] = res.data.data;
        } catch { /* keep previous status */ }
      }));
      if (!cancelled) setNodeInfo((prev) => ({ ...prev, ...fresh }));
    };
    fetchAllStatus();
    const intervalId = setInterval(fetchAllStatus, readPrefs().refreshSec * 1000);
    return () => { cancelled = true; clearInterval(intervalId); };
  }, [nodes]);

  useEffect(() => {
    if (searchParams.get('add') === '1') {
      setAddOpen(true);
      searchParams.delete('add');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // Deep link ?node=<id> (command palette) opens the drawer on Overview.
  useEffect(() => {
    const nodeId = searchParams.get('node');
    if (!nodeId) return;
    const found = nodes.find((x) => String(x.id) === String(nodeId));
    if (found) {
      setDrawer({ node: found, tab: 'overview' });
      searchParams.delete('node');
      setSearchParams(searchParams, { replace: true });
    }
  }, [nodes, searchParams, setSearchParams]);

  const nodeStats = useMemo(() => ({
    total: nodes.length,
    active: nodes.filter((n) => n.status).length,
    inactive: nodes.filter((n) => !n.status).length,
  }), [nodes]);

  const filteredNodes = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    return nodes.filter((n) => {
      if (statusFilter === 'online' && !n.status) return false;
      if (statusFilter === 'offline' && n.status) return false;
      if (!term) return true;
      const meta = nodeMeta(n);
      const hay = `${n.name || ''} ${n.address || ''} ${n.protocol || ''} ${meta.name || ''} ${n.country_code || ''}`.toLowerCase();
      return hay.includes(term);
    });
  }, [nodes, searchTerm, statusFilter]);

  const sortedNodes = useMemo(
    () => [...filteredNodes].sort((a, b) => Number(b.id) - Number(a.id)),
    [filteredNodes],
  );

  const handleCheckStatus = useCallback(async (node) => {
    const key = `check-${node.id}`;
    markBusy(key, true);
    try {
      const response = await apiClient.get(`/nodes/${node.id}/status/`);
      if (response.data?.data) setNodeInfo((prev) => ({ ...prev, [node.id]: response.data.data }));
      addToast(response.data?.msg || t('nodeStatusCheckDone', 'Status check complete.'), 'success');
    } catch (e) {
      addToast(e.response?.data?.detail || t('nodeStatusCheckFailed', 'Failed to check node status.'), 'error');
    } finally {
      markBusy(key, false);
    }
  }, [addToast, t]);

  const handleDownloadAll = useCallback(async (node) => {
    const key = `download-${node.id}`;
    markBusy(key, true);
    try {
      const response = await apiClient.get(`/nodes/ovpn-all/${node.id}`, { responseType: 'blob', timeout: 300000 });
      const blob = new Blob([response.data], { type: 'application/zip' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `ovpn-configs-${node.name}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      addToast(t('nodeDownloadStarted', 'Download started.'), 'success');
    } catch (e) {
      addToast(e.response?.data?.detail || t('nodeExportFailed', 'Could not download the configs.'), 'error');
    } finally {
      markBusy(key, false);
    }
  }, [addToast, t]);

  const handleToggleStatus = useCallback(async (node) => {
    const key = `toggle-${node.id}`;
    markBusy(key, true);
    try {
      const payload = {
        name: node.name,
        address: node.address,
        tunnel_address: node.tunnel_address || null,
        protocol: node.protocol || 'udp',
        ovpn_port: Number(node.ovpn_port || 1194),
        port: Number(node.port || 2083),
        status: !node.status,
        set_new_setting: false,
        use_tls: Boolean(node.use_tls),
      };
      const res = await apiClient.put(`/nodes/${node.id}`, payload);
      if (res.data?.success) {
        addToast(node.status ? t('nodeDisabledToast', 'Node disabled.') : t('nodeEnabledToast', 'Node enabled.'), 'success');
        fetchNodes({ background: true });
      } else {
        addToast(res.data?.msg || t('failedToggleNode', 'Failed to toggle node.'), 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || t('failedToggleNode', 'Failed to toggle node.'), 'error');
    } finally {
      markBusy(key, false);
    }
  }, [addToast, fetchNodes, t]);

  const handleDelete = useCallback((node) => {
    openConfirm(
      t('deleteNode', 'Delete node'),
      t('nodeConfirmDelete', 'Delete "{{name}}"? Its users and configs are removed too. This cannot be undone.', { name: node.name }),
      async () => {
        try {
          const res = await apiClient.delete(`/nodes/${node.id}`);
          addToast(res.data?.success ? t('nodeDeletedSuccess', 'Node deleted successfully.') : (res.data?.msg || t('error', 'Error')), res.data?.success ? 'success' : 'error');
          fetchNodes({ background: true });
        } catch (e) {
          addToast(e.response?.data?.detail || t('error', 'Error'), 'error');
        }
      },
    );
  }, [addToast, fetchNodes, t]);

  const handleNodeCreated = (msg) => {
    setAddOpen(false);
    addToast(msg || t('nodeCreatedSuccess', 'Node created successfully.'), 'success');
    fetchNodes();
  };

  const handleNodeUpdated = (msg) => {
    setEditNode(null);
    addToast(msg || t('nodeUpdatedSuccess', 'Node updated successfully.'), 'success');
    fetchNodes();
  };

  const openDrawer = (node, tab = 'overview') => setDrawer({ node, tab });

  return (
    <div className="nm-page">
      <PageHeader
        title={t('nodes')}
        subtitle={t('nodePageSubtitle', 'Manage the OVNode servers this panel controls.')}
        icon={<FiServer aria-hidden="true" />}
        meta={(
          <span className="nm-meta">
            <strong>{nodeStats.active}</strong>/{nodeStats.total} {t('nodesActive', 'Active Nodes').toLowerCase()}
          </span>
        )}
        actions={(
          <Button variant="primary" icon={<FiPlus aria-hidden="true" />} onClick={() => setAddOpen(true)}>
            {t('addNewNode')}
          </Button>
        )}
      />

      <div className="nm-stats">
        <StatCard label={t('nodesTotal')} value={nodeStats.total} icon={<FiServer aria-hidden="true" />} />
        <StatCard label={t('nodesActive')} value={nodeStats.active} tone="success" icon={<FiCheckCircle aria-hidden="true" />} />
        <StatCard label={t('nodesInactive')} value={nodeStats.inactive} tone="danger" icon={<FiXCircle aria-hidden="true" />} />
      </div>

      <div className="nm-toolbar">
        <label className="nm-search">
          <FiSearch className="nm-search-icon" aria-hidden="true" />
          <input
            type="search"
            className="ui-input nm-search-input"
            placeholder={t('searchNodePlaceholder', 'Search by node name...')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label={t('searchNodePlaceholder', 'Search by node name...')}
          />
        </label>
        <div className="nm-filters" role="group" aria-label={t('status', 'Status')}>
          {[
            { id: 'all', label: t('filterAll', 'All') },
            { id: 'online', label: t('statusOnline', 'Online') },
            { id: 'offline', label: t('statusOffline', 'Offline') },
          ].map((f) => (
            <Button
              key={f.id}
              size="sm"
              variant={statusFilter === f.id ? 'primary' : 'ghost'}
              aria-pressed={statusFilter === f.id}
              onClick={() => setStatusFilter(f.id)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <span className="nm-results" aria-live="polite">
          <strong>{filteredNodes.length}</strong> {t('results', 'results')}
          {(searchTerm || statusFilter !== 'all') && (
            <button type="button" className="nm-clear" onClick={() => { setSearchTerm(''); setStatusFilter('all'); }}>
              {t('clear', 'Clear')}
            </button>
          )}
        </span>
      </div>

      {isLoading && nodes.length === 0 ? (
        <div className="nm-list" role="status" aria-label={t('loading', 'Loading...')}>
          {[0, 1, 2].map((i) => <Card key={i} className="nm-node-skeleton" padded={false}><span className="nm-skel-line" /></Card>)}
        </div>
      ) : loadError && nodes.length === 0 ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchNodes()} retryLabel={t('retry')} />
      ) : nodes.length === 0 ? (
        <EmptyState
          title={t('nodeEmptyTitle', 'No nodes yet')}
          description={t('nodeEmptyBody', 'Add your first OVNode to start. If a node will not connect, the Health page explains the usual causes.')}
          actionLabel={t('nodeOpenHealth', 'Open Health page')}
          onAction={() => navigate('/health')}
        />
      ) : filteredNodes.length === 0 ? (
        <EmptyState
          title={t('noMatchesTitle', 'No matching users')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={() => { setSearchTerm(''); setStatusFilter('all'); }}
        />
      ) : (
        <div className="nm-list">
          {sortedNodes.map((node) => {
            const info = nodeInfo[node.id];
            const live = Number(info?.session_diagnostics?.live_count ?? info?.live_count ?? 0);
            const version = info?.node_info?.version;
            const tls = tlsMeta(info?.tls_mode, t);
            const meta = nodeMeta(node);
            const online = Boolean(node.status) && info?.reachable !== false;
            const transport = (node.protocol || 'udp').toUpperCase();
            return (
              <Card as="article" key={node.id} className="nm-node" padded={false}>
                <div className="nm-node-main">
                  <StatusBadge
                    status={online ? 'online' : 'offline'}
                    label={online ? t('statusOnline') : t('statusOffline')}
                  />
                  <div className="nm-identity">
                    <button
                      type="button"
                      className="nm-name"
                      onClick={() => openDrawer(node)}
                      title={t('clickToManageNode', 'Click to manage node')}
                    >
                      {node.name}
                    </button>
                    <span className="nm-sub">
                      {node.address}:{node.port}
                      {meta.name ? ` · ${meta.name}` : ''}
                    </span>
                  </div>
                  <div className="nm-chips">
                    <Badge tone="neutral">{transport} · {node.ovpn_port ?? '—'}</Badge>
                    {version && <Badge tone="neutral">{t('nodeVersion', 'Version')} {version}</Badge>}
                    {tls && <Badge tone={tls.tone}>{tls.label}</Badge>}
                  </div>
                  <div className="nm-users" title={t('liveSessions', 'Live sessions')}>
                    <FiUsers size={14} aria-hidden="true" />
                    <span className="nm-users-value">{live}</span>
                    <span className="nm-users-label">{t('nodeUsers', 'Users')}</span>
                  </div>
                  <div className="nm-actions" role="group" aria-label={`${node.name} ${t('actions', 'Actions')}`}>
                    <Button
                      variant="ghost" size="sm" icon={<FiRefreshCw size={15} />}
                      loading={Boolean(busy[`check-${node.id}`])}
                      title={t('checkStatus', 'Check Status')} aria-label={`${t('checkStatus', 'Check Status')} ${node.name}`}
                      onClick={() => handleCheckStatus(node)}
                    />
                    <Button
                      variant="ghost" size="sm" icon={<FiFileText size={15} />}
                      title={t('nodeOpenLogs', 'Open logs')} aria-label={`${t('nodeOpenLogs', 'Open logs')} ${node.name}`}
                      onClick={() => openDrawer(node, 'logs')}
                    />
                    <Button
                      variant="ghost" size="sm" icon={<FiEdit2 size={15} />}
                      title={t('editButton', 'Edit')} aria-label={`${t('editButton', 'Edit')} ${node.name}`}
                      onClick={() => setEditNode(node)}
                    />
                    <Button
                      variant="ghost" size="sm" icon={<FiDownload size={15} />}
                      loading={Boolean(busy[`download-${node.id}`])}
                      title={t('downloadAll', 'Download all')} aria-label={`${t('downloadAll', 'Download all')} ${node.name}`}
                      onClick={() => handleDownloadAll(node)}
                    />
                    <Button
                      variant="ghost" size="sm" icon={<FiPower size={15} />}
                      loading={Boolean(busy[`toggle-${node.id}`])}
                      title={node.status ? t('disableUser', 'Disable') : t('enableUser', 'Enable')}
                      aria-label={`${node.status ? t('disableUser', 'Disable') : t('enableUser', 'Enable')} ${node.name}`}
                      onClick={() => handleToggleStatus(node)}
                    />
                    <Button
                      variant="danger" size="sm" icon={<FiTrash2 size={15} />}
                      title={t('deleteButton', 'Delete')} aria-label={`${t('deleteButton', 'Delete')} ${node.name}`}
                      onClick={() => handleDelete(node)}
                    />
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {addOpen && (
        <NodeFormModal isOpen={addOpen} onClose={() => setAddOpen(false)} onSaved={handleNodeCreated} />
      )}
      {editNode && (
        <NodeFormModal
          isOpen={Boolean(editNode)}
          node={editNode}
          onClose={() => setEditNode(null)}
          onSaved={handleNodeUpdated}
        />
      )}
      {drawer && (
        <NodeDrawer
          node={drawer.node}
          initialTab={drawer.tab}
          onClose={() => setDrawer(null)}
          onEdit={(n) => { setDrawer(null); setEditNode(n); }}
          onDelete={(n) => { setDrawer(null); handleDelete(n); }}
          onDownloadAll={handleDownloadAll}
          onChanged={() => fetchNodes({ background: true })}
        />
      )}

      <ConfirmModal
        open={confirm.open}
        onClose={closeConfirm}
        onConfirm={confirm.onConfirm}
        title={confirm.title}
        message={confirm.message}
        confirmLabel={t('deleteButton', 'Delete')}
      />
    </div>
  );
};

export default NodeManagement;
