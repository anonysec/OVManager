import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../services/api';
import { FiActivity, FiRefreshCw, FiDownload, FiCopy, FiCheck, FiFilter } from 'react-icons/fi';
import { fmtDateTime, fmtRelative } from '../utils/time';
import { copyText } from '../utils/clipboard';
import { useToast } from '../context/ToastContext';
import { useLive } from '../context/LiveContext';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import DataTable from '../components/ui/DataTable';
import Modal from '../components/Modal';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import './AuditLog.css';

// Tone per action root. Unknown actions fall back to neutral.
const ACTION_TONES = {
  user: 'info', node: 'accent', admin: 'warning',
  maintenance: 'warning', auth: 'danger', security: 'danger',
};

const toneForAction = (action) => ACTION_TONES[String(action || '').split('.')[0]] || 'neutral';

const PAGE_SIZE_KEY = 'ovmanager-ui-audit-pagesize';

const TIME_RANGES = [
  { id: 'all', seconds: 0 },
  { id: '1h', seconds: 3600 },
  { id: '24h', seconds: 86400 },
  { id: '7d', seconds: 604800 },
  { id: '30d', seconds: 2592000 },
];

const fmtDetail = (d) => {
  if (d == null || d === '') return '—';
  if (typeof d === 'string') return d;
  try { return JSON.stringify(d); } catch { return String(d); }
};

const AuditLog = () => {
  const { t, i18n } = useTranslation();
  const { addToast } = useToast();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [actorFilter, setActorFilter] = useState('all');
  const [actionFilter, setActionFilter] = useState('all');
  const [timeFilter, setTimeFilter] = useState('all');
  const [sort, setSort] = useState({ key: 'ts', dir: 'desc' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => Number(localStorage.getItem(PAGE_SIZE_KEY) || 25) || 25);
  const [detailEvent, setDetailEvent] = useState(null);
  const [copied, setCopied] = useState(false);
  // Wall-clock seconds, updated on an interval. Kept in state so relative
  // times and the time-range filter never call Date.now() during render.
  const [nowTs, setNowTs] = useState(0);

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

  useEffect(() => {
    const update = () => setNowTs(Math.floor(Date.now() / 1000));
    update();
    const id = setInterval(update, 30000);
    return () => clearInterval(id);
  }, []);

  const { subscribe } = useLive();
  useEffect(() => {
    const u = subscribe('tick', () => {});
    return () => u();
  }, [subscribe]);

  // Localized "3h ago" via Intl (falls back to the shared English helper).
  const relative = useMemo(() => {
    let rtf;
    try { rtf = new Intl.RelativeTimeFormat(i18n.language || 'en', { numeric: 'auto' }); } catch { rtf = null; }
    return (ts, now) => {
      if (!ts) return '—';
      // `now` is 0 until the first effect pass — fall back to the shared
      // helper so the very first paint cannot show a nonsense distance.
      if (!rtf || !now) return fmtRelative(new Date(Number(ts) * 1000).toISOString());
      const diff = Math.round(Number(ts) - now);
      const abs = Math.abs(diff);
      if (abs < 45) return rtf.format(0, 'second');
      if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
      if (abs < 604800) return rtf.format(Math.round(diff / 86400), 'day');
      if (abs < 2592000) return rtf.format(Math.round(diff / 604800), 'week');
      if (abs < 31536000) return rtf.format(Math.round(diff / 2592000), 'month');
      return rtf.format(Math.round(diff / 31536000), 'year');
    };
  }, [i18n.language]);

  const actors = useMemo(() => {
    const set = new Set();
    for (const e of events) set.add(e.actor || 'system');
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [events]);

  const actions = useMemo(() => {
    const counts = new Map();
    for (const e of events) {
      const key = String(e.action || 'unknown');
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [events]);

  const filtersActive = query !== '' || actorFilter !== 'all' || actionFilter !== 'all' || timeFilter !== 'all';

  const clearFilters = () => {
    setQuery('');
    setActorFilter('all');
    setActionFilter('all');
    setTimeFilter('all');
    setPage(1);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const range = TIME_RANGES.find((r) => r.id === timeFilter);
    const cutoff = range && range.seconds && nowTs ? nowTs - range.seconds : 0;
    return events.filter((e) => {
      if (actionFilter !== 'all' && String(e.action || '') !== actionFilter) return false;
      if (actorFilter !== 'all' && (e.actor || 'system') !== actorFilter) return false;
      if (cutoff && Number(e.ts || 0) < cutoff) return false;
      if (!q) return true;
      const hay = `${e.actor || ''} ${e.action || ''} ${e.target || ''} ${fmtDetail(e.detail)}`.toLowerCase();
      return hay.includes(q);
    });
  }, [events, query, actorFilter, actionFilter, timeFilter, nowTs]);

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
      render: (e) => {
        const iso = e.ts ? new Date(e.ts * 1000).toISOString() : '';
        return (
          <span className="adt-time" title={fmtDateTime(iso)}>
            <span className="adt-time-rel">{relative(e.ts, nowTs)}</span>
            <span className="adt-time-abs">{fmtDateTime(iso)}</span>
          </span>
        );
      },
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
      render: (e) => <Badge tone={toneForAction(e.action)}>{e.action || '—'}</Badge>,
    },
    {
      key: 'target', label: t('user', 'Target'), sortable: true, hideOnMobile: true,
      render: (e) => e.target || '—',
    },
    {
      key: 'detail', label: t('node', 'Detail'), hideOnMobile: true,
      render: (e) => (
        <button type="button" className="dt-rowlink" onClick={() => setDetailEvent(e)} title={t('viewDetails', 'View details')}>
          <span className="dt-cell-sub adt-detail">
            {fmtDetail(e.detail)}
          </span>
        </button>
      ),
    },
  ], [t, relative, nowTs]);

  return (
    <div id="audit-view" className="view adt-page">
      <div className="adt-head">
        <div>
          <h2 className="adt-title"><FiActivity aria-hidden="true" /> {t('navAudit', 'Audit Log')}</h2>
          <p className="adt-subtitle">{t('auditSubtitle', 'Who changed what, and when. Entries are scoped to the admins you can see.')}</p>
        </div>
        <div className="adt-head-actions">
          <Button
            variant="secondary" size="sm"
            icon={<FiDownload size={13} aria-hidden="true" />}
            onClick={handleExportCsv}
            disabled={filtered.length === 0}
          >
            {t('exportCsv', 'CSV')}
          </Button>
          <Button
            variant="secondary" size="sm"
            icon={<FiRefreshCw size={13} aria-hidden="true" />}
            onClick={() => load()}
          >
            {t('refresh', 'Refresh')}
          </Button>
        </div>
      </div>

      <div className="adt-filters">
        <label className="search-field adt-search">
          <input
            type="search"
            className="search-input"
            placeholder={t('auditSearch', 'Search actor, action, target, detail…')}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }}
            aria-label={t('auditSearch', 'Search audit log')}
          />
        </label>

        <label className="adt-filter">
          <span className="adt-filter-label">{t('auditActorFilter', 'Actor')}</span>
          <select
            className="ui-input adt-select"
            value={actorFilter}
            onChange={(e) => { setActorFilter(e.target.value); setPage(1); }}
          >
            <option value="all">{t('auditAllActors', 'All actors')}</option>
            {actors.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>

        <label className="adt-filter">
          <span className="adt-filter-label">{t('auditActionFilter', 'Action')}</span>
          <select
            className="ui-input adt-select"
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(1); }}
          >
            <option value="all">{t('auditAllActions', 'All actions')}</option>
            {actions.map(([action, count]) => (
              <option key={action} value={action}>{action} ({count})</option>
            ))}
          </select>
        </label>

        <label className="adt-filter">
          <span className="adt-filter-label">{t('auditTimeFilter', 'Time range')}</span>
          <select
            className="ui-input adt-select"
            value={timeFilter}
            onChange={(e) => { setTimeFilter(e.target.value); setPage(1); }}
          >
            {TIME_RANGES.map((r) => (
              <option key={r.id} value={r.id}>
                {t(`auditTime_${r.id}`, {
                  all: 'All time', '1h': 'Last hour', '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days',
                }[r.id])}
              </option>
            ))}
          </select>
        </label>

        <div className="results-meta" aria-live="polite">
          <FiFilter aria-hidden="true" />
          <strong>{filtered.length}</strong> {t('results', 'results')}
          {filtersActive && (
            <button type="button" className="toolbar-clear" onClick={clearFilters}>
              {t('clear', 'Clear')}
            </button>
          )}
        </div>
      </div>

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
          onAction={clearFilters}
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
