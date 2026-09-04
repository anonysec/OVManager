import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { FiActivity, FiRefreshCw, FiDownload, FiCopy, FiCheck } from 'react-icons/fi';
import { fmtDateTime } from '../utils/time';
import { copyText } from '../utils/clipboard';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import DataTable from '../components/ui/DataTable';
import Modal from '../components/Modal';

const ACTION_COLORS = {
  'user.create': 'ok', 'user.delete': 'danger', 'user.update': 'info',
  'user.status': 'info', 'user.disconnect': 'warn', 'user.reset': 'info',
  'user.extend': 'ok', 'user.restore': 'ok',
  'node.create': 'ok', 'node.delete': 'danger', 'node.update': 'info',
  'maintenance.backup': 'info', 'maintenance.restore': 'warn',
};

const PAGE_SIZE_KEY = 'ovmanager-ui-audit-pagesize';

const fmtDetail = (d) => {
  if (d == null || d === '') return '—';
  if (typeof d === 'string') return d;
  try { return JSON.stringify(d); } catch { return String(d); }
};

const AuditLog = () => {
  const { t } = useTranslation();
  const { addToast } = useToast();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [actionFilter, setActionFilter] = useState('all');
  const [sort, setSort] = useState({ key: 'ts', dir: 'desc' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25);
  const [detailEvent, setDetailEvent] = useState(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async ({ background = false } = {}) => {
    if (!background) { setLoading(true); setError(''); }
    try {
      const res = await apiClient.get('/activity/', { params: { limit: 200 } });
      if (res.data.success) { setEvents(res.data.data || []); setError(''); }
      else if (!background) setError(t('failedToLoad', 'Failed to load activity.'));
    } catch (e) {
      if (background) return;
      const detail = e.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map((d) => d.msg || JSON.stringify(d)).join(', '));
      } else if (typeof detail === 'object' && detail !== null) {
        setError(JSON.stringify(detail));
      } else {
        setError(detail || t('failedToLoad', 'Failed to load activity.'));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const { subscribe } = useLive();
  useEffect(() => {
    const u = subscribe('tick', () => {});
    return () => u();
  }, [subscribe]);

  const actionKinds = useMemo(() => {
    const kinds = new Map();
    for (const e of events) {
      const root = String(e.action || '').split('.')[0] || 'other';
      kinds.set(root, (kinds.get(root) || 0) + 1);
    }
    return [...kinds.entries()].sort((a, b) => b[1] - a[1]);
  }, [events]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return events.filter((e) => {
      if (actionFilter !== 'all' && !String(e.action || '').startsWith(actionFilter)) return false;
      if (!q) return true;
      const hay = `${e.actor || ''} ${e.action || ''} ${e.target || ''} ${fmtDetail(e.detail)}`.toLowerCase();
      return hay.includes(q);
    });
  }, [events, query, actionFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const mul = sort.dir === 'desc' ? -1 : 1;
    arr.sort((a, b) => {
      let va; let vb;
      switch (sort.key) {
        case 'ts': va = Number(a.ts || 0); vb = Number(b.ts || 0); break;
        case 'actor': va = (a.actor || '').toLowerCase(); vb = (b.actor || '').toLowerCase(); break;
        case 'action': va = (a.action || '').toLowerCase(); vb = (b.action || '').toLowerCase(); break;
        case 'target': va = (a.target || '').toLowerCase(); vb = (b.target || '').toLowerCase(); break;
        default: va = a[sort.key]; vb = b[sort.key];
      }
      if (va < vb) return -1 * mul;
      if (va > vb) return 1 * mul;
      return 0;
    });
    return arr;
  }, [filtered, sort]);

  const paged = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, page, pageSize]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
    if (page > totalPages) setPage(totalPages);
  }, [sorted.length, pageSize, page]);

  const onSort = useCallback((key) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'ts' ? 'desc' : 'asc' }));
  }, []);

  const handleExportCsv = useCallback(() => {
    const esc = (v) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const head = ['time', 'actor', 'action', 'target', 'detail'];
    const rows = filtered.map((e) => [
      e.ts ? new Date(e.ts * 1000).toISOString() : '',
      e.actor || '', e.action || '', e.target || '', fmtDetail(e.detail),
    ]);
    const csv = [head, ...rows].map((r) => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `ovmanager-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    addToast(t('exported', 'CSV exported'), 'success');
  }, [filtered, addToast, t]);

  const copyDetail = async () => {
    if (!detailEvent) return;
    const ok = await copyText(fmtDetail(detailEvent.detail));
    setCopied(ok);
    setTimeout(() => setCopied(false), 1500);
  };

  const columns = useMemo(() => [
    {
      key: 'ts', label: t('th_lastOnline', 'Time'), sortable: true,
      render: (e) => <span className="dt-num">{e.ts ? fmtDateTime(new Date(e.ts * 1000).toISOString()) : '—'}</span>,
    },
    {
      key: 'actor', label: t('th_admin', 'Actor'), sortable: true,
      render: (e) => (
        <span className="dt-cell-main">
          <span className="dt-avatar" aria-hidden="true">{String(e.actor || 's').slice(0, 1).toUpperCase()}</span>
          <span className="dt-cell-title">{e.actor || 'system'}</span>
        </span>
      ),
    },
    {
      key: 'action', label: t('status', 'Action'), sortable: true,
      render: (e) => <span className={`status-pill ${ACTION_COLORS[e.action] || 'muted'}`}>{e.action}</span>,
    },
    {
      key: 'target', label: t('user', 'Target'), sortable: true, hideOnMobile: true,
      render: (e) => e.target || '—',
    },
    {
      key: 'detail', label: t('node', 'Detail'), hideOnMobile: true,
      render: (e) => (
        <button type="button" className="dt-rowlink" onClick={() => setDetailEvent(e)} title={t('viewDetails', 'View details')}>
          <span className="dt-cell-sub" style={{ display: 'block', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {fmtDetail(e.detail)}
          </span>
        </button>
      ),
    },
  ], [t]);

  return (
    <div id="audit-view" className="view">
      <div className="view-header">
        <h2><FiActivity aria-hidden="true" /> {t('navAudit', 'Audit Log')}</h2>
        <div className="view-header-actions">
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleExportCsv} disabled={filtered.length === 0}>
            <FiDownload size={13} aria-hidden="true" /> {t('exportCsv', 'CSV')}
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => load()} title={t('refresh', 'Refresh')}>
            <FiRefreshCw size={13} aria-hidden="true" /> {t('refresh', 'Refresh')}
          </button>
        </div>
      </div>

      <div className="search-with-filters">
        <label className="search-field" style={{ flex: 1, maxWidth: 320 }}>
          <input
            type="search"
            className="search-input"
            placeholder={t('auditSearch', 'Search actor, action, target, detail…')}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
            aria-label={t('auditSearch', 'Search audit log')}
          />
        </label>
        <div className="results-meta" aria-live="polite">
          <strong>{filtered.length}</strong> {t('results', 'results')}
          {(query || actionFilter !== 'all') && (
            <button type="button" className="toolbar-clear" onClick={() => { setQuery(''); setActionFilter('all'); setPage(1); }}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

      {actionKinds.length > 1 && (
        <div className="user-filter-chips" role="group" aria-label={t('filterByAction', 'Filter by action')}>
          <button type="button" className={`filter-chip${actionFilter === 'all' ? ' active' : ''}`} aria-pressed={actionFilter === 'all'} onClick={() => { setActionFilter('all'); setPage(1); }}>
            {t('filterAll', 'All')} <span className="count">{events.length}</span>
          </button>
          {actionKinds.map(([kind, count]) => (
            <button key={kind} type="button" className={`filter-chip${actionFilter === kind ? ' active' : ''}`} aria-pressed={actionFilter === kind} onClick={() => { setActionFilter(kind); setPage(1); }}>
              {kind} <span className="count">{count}</span>
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <DataTable columns={columns} rows={[]} loading />
      ) : error ? (
        <ErrorState title={t('error', 'Error')} message={error} onRetry={() => load()} retryLabel={t('retry', 'Retry')} />
      ) : events.length === 0 ? (
        <EmptyState
          title={t('noActivity', 'No activity recorded yet')}
          description={t('activityWillAppear', 'User and node changes will appear here as they happen.')}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={t('noMatchesTitle', 'No matching entries')}
          description={t('noMatchesBody', 'Try a different search term or clear the active filter.')}
          actionLabel={t('clearFilters', 'Clear filters')}
          onAction={() => { setQuery(''); setActionFilter('all'); }}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={paged}
          rowKey={(r) => String(r.id ?? `${r.ts}-${r.actor}-${r.action}`)}
          sortKey={sort.key}
          sortDir={sort.dir}
          onSort={onSort}
          page={page}
          pageSize={pageSize}
          total={sorted.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => { setPageSize(n); localStorage.setItem(PAGE_SIZE_KEY, String(n)); setPage(1); }}
          caption={t('navAudit', 'Audit Log')}
        />
      )}

      <Modal isOpen={!!detailEvent} onClose={() => setDetailEvent(null)} title={`${detailEvent?.action || ''} — ${detailEvent?.target || ''}`} size="medium">
        {detailEvent && (
          <div className="udetail">
            <div className="udetail-grid">
              <div className="udetail-cell"><div><span className="ud-k">{t('th_lastOnline', 'Time')}</span><strong>{detailEvent.ts ? fmtDateTime(new Date(detailEvent.ts * 1000).toISOString()) : '—'}</strong></div></div>
              <div className="udetail-cell"><div><span className="ud-k">{t('th_admin', 'Actor')}</span><strong>{detailEvent.actor || 'system'}</strong></div></div>
            </div>
            <div className="udetail-sub">
              <span className="ud-k">{t('node', 'Detail')}</span>
              <div className="udetail-linkrow">
                <code className="udetail-link" style={{ whiteSpace: 'pre-wrap' }}>{fmtDetail(detailEvent.detail)}</code>
                <button type="button" className="code-copy" onClick={copyDetail} aria-label={t('copyLink', 'Copy')}>
                  {copied ? <FiCheck /> : <FiCopy />}
                </button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default AuditLog;
