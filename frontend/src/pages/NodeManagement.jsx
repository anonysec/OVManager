import { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FiServer, FiCheckCircle, FiXCircle, FiSearch, FiPlus, FiDownload, FiGlobe, FiEdit2, FiTrash2, FiRefreshCw, FiEye } from 'react-icons/fi';
import NodeDrawer from '../components/NodeDrawer';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';
import { nodeMeta } from '../utils/geo';
import NodeFormModal from '../components/NodeFormModal';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import DataTable from '../components/ui/DataTable';
import StatusBadge from '../components/ui/StatusBadge';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import ConfirmModal from '../components/ConfirmModal';

const PAGE_SIZE_KEY = 'ovmanager-ui-nodes-pagesize';

const NodeManagement = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [nodes, setNodes] = useState([]);
  const [nodeInfo, setNodeInfo] = useState({});
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirm, setConfirm] = useState({ open: false, title: '', message: '', onConfirm: null });
  const openConfirm = (title, message, onConfirm) => setConfirm({ open: true, title, message, onConfirm });
  const closeConfirm = () => setConfirm(c => ({ ...c, open: false }));
  const [loadError, setLoadError] = useState(false);
  const [drawerNode, setDrawerNode] = useState(null);
  const [grouped, setGrouped] = useState(() => localStorage.getItem('ovmanager-ui-node-grouped') === '1');
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sort, setSort] = useState({ key: 'name', dir: 'asc' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [density] = useState(() => localStorage.getItem('ovmanager-ui-density') || 'comfort');

  const fetchNodes = useCallback(async ({ background = false } = {}) => {
    if (!background) setIsLoading(true);
    setLoadError(false);
    try {
      const response = await apiClient.get('/nodes/');
      if (response.data.success) {
        setNodes(asList(response.data, 'nodes'));
      } else {
        setLoadError(true);
      }
    } catch (error) {
      console.error('Error fetching nodes:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const { subscribe } = useLive();
  useEffect(() => {
    const u = subscribe('nodes.changed', () => fetchNodes({ background: true }));
    return () => u();
  }, [subscribe, fetchNodes]);

  useEffect(() => { fetchNodes(); }, [fetchNodes]);

  useEffect(() => {
    if (searchParams.get('add') === '1') {
      setIsAddModalOpen(true);
      searchParams.delete('add');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!nodes || nodes.length === 0) return undefined;
    let cancelled = false;
    const fetchAllNodeStatus = async () => {
      const info = {};
      await Promise.all(nodes.map(async (node) => {
        try {
          const res = await apiClient.get(`/nodes/${node.id}/status/`);
          if (res.data.success && res.data.data) {
            info[node.id] = res.data.data;
          } else if (res.data.success && res.data.node_info) {
            info[node.id] = res.data;
          }
        } catch { /* keep previous */ }
      }));
      if (!cancelled) setNodeInfo((prev) => ({ ...prev, ...info }));
    };
    fetchAllNodeStatus();
    const intervalId = setInterval(fetchAllNodeStatus, 30000);
    return () => { cancelled = true; clearInterval(intervalId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length]);

  const nodeStats = useMemo(() => ({
    total: nodes.length,
    active: nodes.filter(n => n.status).length,
    inactive: nodes.filter(n => !n.status).length,
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

  const sortedNodes = useMemo(() => {
    const arr = [...filteredNodes];
    const mul = sort.dir === 'desc' ? -1 : 1;
    const val = (n) => {
      switch (sort.key) {
        case 'name': return (n.name || '').toLowerCase();
        case 'address': return (n.address || '').toLowerCase();
        case 'protocol': return (n.protocol || '').toLowerCase();
        case 'ovpn_port': return Number(n.ovpn_port || 0);
        case 'status': return n.status ? 1 : 0;
        case 'country': return (nodeMeta(n).name || '').toLowerCase();
        default: return n[sort.key];
      }
    };
    arr.sort((a, b) => {
      if (grouped) {
        const ga = nodeMeta(a).name || '';
        const gb = nodeMeta(b).name || '';
        if (ga !== gb) return ga.localeCompare(gb);
      }
      const va = val(a); const vb = val(b);
      if (va < vb) return -1 * mul;
      if (va > vb) return 1 * mul;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
    return arr;
  }, [filteredNodes, sort, grouped]);

  const pagedNodes = useMemo(() => {
    if (grouped) return sortedNodes;
    const start = (page - 1) * pageSize;
    return sortedNodes.slice(start, start + pageSize);
  }, [sortedNodes, page, pageSize, grouped]);

  const groupedSections = useMemo(() => {
    if (!grouped) return null;
    const map = new Map();
    for (const n of sortedNodes) {
      const country = nodeMeta(n).name || t('unknown', 'Unknown');
      if (!map.has(country)) map.set(country, []);
      map.get(country).push(n);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [grouped, sortedNodes, t]);

  const onSort = useCallback((key) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));
  }, []);

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
          const res = await apiClient.delete(`/nodes/${node.id}`);
          addToast(res.data?.success ? t('nodeDeletedSuccess', 'Node deleted successfully.') : (res.data?.msg || t('error')), res.data?.success ? 'success' : 'error');
          setSelected((prev) => { const n = new Set(prev); n.delete(String(node.id)); return n; });
          fetchNodes({ background: true });
        } catch { addToast(t('error'), 'error'); }
      }
    );
  };

  const handleToggleStatus = useCallback(async (node) => {
    try {
      const payload = {
        name: node.name,
        address: node.address,
        tunnel_address: node.tunnel_address || null,
        protocol: node.protocol || 'tcp',
        ovpn_port: Number(node.ovpn_port || 1194),
        port: Number(node.port || 2083),
        status: !node.status,
        set_new_setting: false,
        use_tls: Boolean(node.use_tls),
      };
      const res = await apiClient.put(`/nodes/${node.id}`, payload);
      if (res.data?.success) {
        addToast(!node.status ? t('nodeEnabledToast', 'Node enabled.') : t('nodeDisabledToast', 'Node disabled.'), 'success');
        fetchNodes({ background: true });
      } else {
        addToast(res.data?.msg || t('failedToggleNode', 'Failed to toggle node.'), 'error');
      }
    } catch (e) {
      addToast(e.response?.data?.detail || t('failedToggleNode', 'Failed to toggle node.'), 'error');
    }
  }, [addToast, fetchNodes, t]);

  const handleCheckStatus = async (nodeId) => {
    try {
      const response = await apiClient.get(`/nodes/${nodeId}/status/`);
      addToast(response.data.msg || t('statusCheckDone', 'Status check complete.'), 'success');
      fetchNodes({ background: true });
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
    const rows = filteredNodes.map(n => [n.id, n.name, n.address, n.port, n.protocol, n.ovpn_port, n.status ? 'active' : 'inactive', nodeMeta(n).name || n.country_code || '']);
    const csv = [head, ...rows].map(r => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `ovmanager-nodes-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    addToast(t('exported'), 'success');
  };

  const handleNodeUpdated = (msg) => {
    setIsEditModalOpen(false);
    setSelectedNode(null);
    addToast(msg || t('nodeUpdatedSuccess'), 'success');
    fetchNodes();
  };

  const runBulkDelete = async () => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    let ok = 0; let fail = 0;
    for (const id of selected) {
      try {
        const res = await apiClient.delete(`/nodes/${id}`);
        if (res.data?.success) ok += 1; else fail += 1;
      } catch { fail += 1; }
    }
    setBulkBusy(false);
    setSelected(new Set());
    fetchNodes({ background: true });
    addToast(fail === 0 ? t('bulkDeleteDone', 'Deleted {{ok}} nodes.', { ok }) : t('bulkPartial', '{{ok}} done, {{fail}} failed.', { ok, fail }), fail === 0 ? 'success' : 'warning');
  };

  const columns = useMemo(() => [
    {
      key: 'name', label: t('th_nodeName', 'Node'), sortable: true,
      render: (n) => {
        const meta = nodeMeta(n);
        const live = nodeInfo[n.id];
        const sessions = Number(live?.session_diagnostics?.live_count ?? live?.live_count ?? 0);
        return (
          <button type="button" className="dt-rowlink" onClick={() => setDrawerNode(n)} title={t('clickToManageNode', 'Click to manage node')}>
            <span className="dt-cell-main">
              <span className="dt-avatar" aria-hidden="true">{String(n.name || '?').slice(0, 2).toUpperCase()}</span>
              <span style={{ minWidth: 0 }}>
                <span className="dt-cell-title">{n.name}</span>
                <br />
                <span className="dt-cell-sub">{n.address}:{n.port} · {meta.name}{sessions > 0 ? ` · ${sessions} live` : ''}</span>
              </span>
            </span>
          </button>
        );
      },
    },
    {
      key: 'status', label: t('th_status', 'Status'), sortable: true,
      render: (n) => <StatusBadge status={n.status ? 'online' : 'offline'} label={n.status ? t('statusOnline') : t('statusOffline')} />,
    },
    {
      key: 'protocol', label: t('th_protocol', 'Protocol'), sortable: true, hideOnMobile: true,
      render: (n) => <span className="dt-num">{(n.protocol || 'tcp').toUpperCase()} / {n.ovpn_port ?? '—'}</span>,
    },
    {
      key: 'country', label: t('th_location', 'Location'), sortable: true, hideOnMobile: true,
      render: (n) => nodeMeta(n).name || '—',
    },
    {
      key: 'actions', label: t('th_actions', 'Actions'),
      render: (n) => (
        <span className="dt-actions" role="group" aria-label={`${n.name} ${t('actions', 'Actions')}`}>
          <button type="button" className="dt-icon-btn" title={t('view', 'View')} aria-label={`${t('view', 'View')} ${n.name}`} onClick={() => setDrawerNode(n)}><FiEye size={15} /></button>
          <button type="button" className="dt-icon-btn" title={t('checkStatus', 'Check status')} aria-label={`${t('checkStatus', 'Check status')} ${n.name}`} onClick={() => handleCheckStatus(n.id)}><FiRefreshCw size={15} /></button>
          <button type="button" className="dt-icon-btn" title={t('downloadAll', 'Download all')} aria-label={`${t('downloadAll', 'Download all')} ${n.name}`} onClick={() => handleDownloadAllConfigs(n)}><FiDownload size={15} /></button>
          <button type="button" className="dt-icon-btn" title={t('editButton', 'Edit')} aria-label={`${t('editButton', 'Edit')} ${n.name}`} onClick={() => handleOpenEditModal(n)}><FiEdit2 size={15} /></button>
          <button type="button" className="dt-icon-btn is-danger" title={t('deleteButton', 'Delete')} aria-label={`${t('deleteButton', 'Delete')} ${n.name}`} onClick={() => handleDelete(n)}><FiTrash2 size={15} /></button>
        </span>
      ),
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t, nodeInfo]);

  const allPageKeys = pagedNodes.map((n) => String(n.id));
  const allSelected = allPageKeys.length > 0 && allPageKeys.every((k) => selected.has(k));
  const someSelected = allPageKeys.some((k) => selected.has(k));

  const tableProps = {
    columns,
    sortKey: sort.key,
    sortDir: sort.dir,
    onSort,
    selectable: true,
    selectedKeys: selected,
    allSelected,
    someSelected: someSelected && !allSelected,
    onSelectAll: (checked) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (checked) allPageKeys.forEach((k) => next.add(k));
        else allPageKeys.forEach((k) => next.delete(k));
        return next;
      });
    },
    onSelectRow: (k, checked) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (checked) next.add(String(k));
        else next.delete(String(k));
        return next;
      });
    },
    density,
  };

  return (
    <div id="nodes-view" className="view">
      <div className="view-header">
        <h2>{t('nodes')}</h2>
        <div className="view-header-actions">
          <button type="button" className={`btn btn-secondary btn-sm${grouped ? ' btn-active' : ''}`} aria-pressed={grouped} onClick={() => { setGrouped(!grouped); localStorage.setItem('ovmanager-ui-node-grouped', grouped ? '0' : '1'); }} title={t('groupByCountry')}>
            <FiGlobe aria-hidden="true" /> {t('groupByCountry', 'Group')}
          </button>
          <button type="button" onClick={handleExportCsv} className="btn btn-secondary btn-sm" aria-label={t('exportCsv')}>
            <FiDownload aria-hidden="true" /> {t('exportCsv', 'CSV')}
          </button>
          <button type="button" onClick={() => setIsAddModalOpen(true)} className="btn btn-primary btn-sm">
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
        <label className="search-field" style={{ flex: 1, maxWidth: 320 }}>
          <FiSearch className="search-icon" aria-hidden="true" />
          <input
            type="search"
            placeholder={t('searchNodePlaceholder', 'Search by name…')}
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setPage(1); }}
            className="search-input"
            aria-label={t('searchNodePlaceholder', 'Search by name…')}
          />
        </label>
        <div className="user-filter-chips" role="group" aria-label={t('status', 'Status')}>
          {[
            { id: 'all', label: t('filterAll', 'All') },
            { id: 'online', label: t('statusOnline', 'Online') },
            { id: 'offline', label: t('statusOffline', 'Offline') },
          ].map((f) => (
            <button key={f.id} type="button" className={`filter-chip${statusFilter === f.id ? ' active' : ''}`} aria-pressed={statusFilter === f.id} onClick={() => { setStatusFilter(f.id); setPage(1); }}>
              {f.label}
            </button>
          ))}
        </div>
        <div className="results-meta" aria-live="polite">
          <strong>{filteredNodes.length}</strong> {t('results', 'results')}
          {(searchTerm || statusFilter !== 'all') && (
            <button type="button" className="toolbar-clear" onClick={() => { setSearchTerm(''); setStatusFilter('all'); }}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

      {selected.size > 0 && (
        <div className="dt-bulkbar" role="toolbar" aria-label={t('bulkActions', 'Bulk actions')}>
          <strong>{t('selectedCount', '{{count}} selected', { count: selected.size })}</strong>
          <button
            type="button" className="btn btn-danger btn-sm" disabled={bulkBusy}
            onClick={() => openConfirm(t('deleteButton', 'Delete'), t('confirmBulkDelete', 'Delete {{count}} selected nodes? This cannot be undone.', { count: selected.size }), runBulkDelete)}
          >
            <FiTrash2 size={13} /> {t('delete', 'Delete')}
          </button>
          <button type="button" className="toolbar-clear" onClick={() => setSelected(new Set())}>{t('clear', 'Clear')}</button>
        </div>
      )}

      {isLoading ? (
        <DataTable columns={columns} rows={[]} loading density={density} />
      ) : loadError ? (
        <ErrorState title={t('loadError')} message={t('loadErrorDetail')} onRetry={() => fetchNodes()} retryLabel={t('retry')} />
      ) : nodes.length === 0 ? (
        <EmptyState title={t('noNodes')} description={t('noNodesBody')} actionLabel={t('addNewNode')} onAction={() => setIsAddModalOpen(true)} />
      ) : filteredNodes.length === 0 ? (
        <EmptyState
          title={t('noMatchesTitle', 'No matching nodes')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={() => { setSearchTerm(''); setStatusFilter('all'); }}
        />
      ) : grouped ? (
        <div className="dt-grouped">
          {groupedSections.map(([country, list]) => (
            <section key={country} aria-label={country} style={{ marginBottom: 16 }}>
              <h3 className="dt-group-title">{country} <span className="count">{list.length}</span></h3>
              <DataTable columns={columns} rows={list} rowKey={(r) => String(r.id)} {...tableProps} page={1} pageSize={list.length} total={list.length} onPageChange={null} />
            </section>
          ))}
        </div>
      ) : (
        <DataTable
          columns={columns}
          rows={pagedNodes}
          rowKey={(r) => String(r.id)}
          page={page}
          pageSize={pageSize}
          total={sortedNodes.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); localStorage.setItem(PAGE_SIZE_KEY, String(n)); setPage(1); }}
          {...tableProps}
          caption={t('nodes', 'Nodes')}
        />
      )}

      {isAddModalOpen && (
        <NodeFormModal isOpen={isAddModalOpen} onClose={() => setIsAddModalOpen(false)} onSaved={handleNodeCreated} />
      )}
      {isEditModalOpen && selectedNode && (
        <NodeFormModal isOpen={isEditModalOpen} node={selectedNode} onClose={() => { setIsEditModalOpen(false); setSelectedNode(null); }} onSaved={handleNodeUpdated} />
      )}
      {drawerNode && (
        <NodeDrawer
          node={drawerNode}
          onClose={() => setDrawerNode(null)}
          onEdit={(n) => { setDrawerNode(null); handleOpenEditModal(n); }}
          onDelete={(idOrNode) => {
            const target = typeof idOrNode === 'object' ? idOrNode : nodes.find((x) => String(x.id) === String(idOrNode)) || { id: idOrNode, name: String(idOrNode) };
            setDrawerNode(null);
            handleDelete(target);
          }}
          onToggleStatus={(n) => { const target = typeof n === 'object' ? n : nodes.find((x) => String(x.id) === String(n)); if (target) handleToggleStatus(target); }}
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
