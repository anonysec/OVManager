import { FiChevronUp, FiChevronDown, FiChevronsLeft, FiChevronsRight, FiChevronLeft, FiChevronRight } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';
import { SkeletonTable } from './Skeleton';
import './DataTable.css';

const DataTable = ({
  columns,
  rows = [],
  rowKey = (r, i) => r.id ?? r.uuid ?? r.username ?? r.name ?? i,
  sortKey = null,
  sortDir = 'asc',
  onSort = null,
  selectable = false,
  selectedKeys = null,
  onSelectAll = null,
  onSelectRow = null,
  allSelected = false,
  someSelected = false,
  loading = false,
  skeletonRows = 8,
  page = 1,
  pageSize = 25,
  total = null,
  onPageChange = null,
  onPageSizeChange = null,
  pageSizeOptions = [10, 25, 50, 100],
  empty = null,
  caption = null,
  density = 'comfort',
}) => {
  const { t } = useTranslation();
  const totalRows = total ?? rows.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const from = totalRows === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const to = Math.min(totalRows, safePage * pageSize);

  if (loading) {
    return <SkeletonTable rows={skeletonRows} cols={columns.length + (selectable ? 1 : 0)} />;
  }

  if (!rows.length && empty) return empty;

  return (
    <div className={`dt-wrap dt-${density}`}>
      <div className="dt-scroll" role="region" aria-label={caption || t('table', 'Table')} tabIndex={0}>
        <table className="dt-table">
          {caption && <caption className="dt-caption">{caption}</caption>}
          <thead>
            <tr>
              {selectable && (
                <th scope="col" className="dt-th dt-col-check">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                    onChange={(e) => onSelectAll?.(e.target.checked)}
                    aria-label={t('selectAll', 'Select all')}
                  />
                </th>
              )}
              {columns.map((c) => {
                const active = sortKey === c.key;
                const ariaSort = !c.sortable ? undefined : active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none';
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={ariaSort}
                    className={`dt-th${c.className ? ` ${c.className}` : ''}${c.sortable ? ' dt-sortable' : ''}${c.hideOnMobile ? ' dt-hide-mobile' : ''}`}
                  >
                    {c.sortable ? (
                      <button
                        type="button"
                        className="dt-sort-btn"
                        onClick={() => onSort?.(c.key)}
                        aria-label={`${c.label}: ${t('sort', 'sort')}`}
                      >
                        <span>{c.label}</span>
                        <span className="dt-sort-ico" aria-hidden="true">
                          {active ? (sortDir === 'asc' ? <FiChevronUp size={13} /> : <FiChevronDown size={13} />) : <FiChevronDown size={13} className="dt-sort-idle" />}
                        </span>
                      </button>
                    ) : c.label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const k = rowKey(row, i);
              const checked = selectedKeys?.has?.(String(k)) ?? false;
              return (
                <tr key={k} className={`dt-row${checked ? ' dt-selected' : ''}`}>
                  {selectable && (
                    <td className="dt-td dt-col-check">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => onSelectRow?.(k, e.target.checked)}
                        aria-label={t('selectRow', 'Select row')}
                      />
                    </td>
                  )}
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={`dt-td${c.className ? ` ${c.className}` : ''}${c.hideOnMobile ? ' dt-hide-mobile' : ''}`}
                      data-label={typeof c.label === 'string' ? c.label : undefined}
                    >
                      {c.render ? c.render(row) : (row[c.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {onPageChange && totalRows > 0 && (
        <div className="dt-footer">
          <span className="dt-range" aria-live="polite">
            {t('showingRange', 'Showing {{from}}–{{to}} of {{total}}', { from, to, total: totalRows })}
          </span>
          <div className="dt-pager">
            {onPageSizeChange && (
              <label className="dt-pagesize">
                <span>{t('rowsPerPage', 'Rows per page')}</span>
                <select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
                  {pageSizeOptions.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            )}
            <div className="dt-pagebtns" role="group" aria-label={t('pagination', 'Pagination')}>
              <button type="button" className="dt-pbtn" disabled={safePage <= 1} onClick={() => onPageChange(1)} aria-label={t('firstPage', 'First page')}><FiChevronsLeft size={14} /></button>
              <button type="button" className="dt-pbtn" disabled={safePage <= 1} onClick={() => onPageChange(safePage - 1)} aria-label={t('prev', 'Previous')}><FiChevronLeft size={14} /></button>
              <span className="dt-pagenum" aria-live="polite">{t('pageOf', 'Page {{page}} of {{total}}', { page: safePage, total: totalPages })}</span>
              <button type="button" className="dt-pbtn" disabled={safePage >= totalPages} onClick={() => onPageChange(safePage + 1)} aria-label={t('next', 'Next')}><FiChevronRight size={14} /></button>
              <button type="button" className="dt-pbtn" disabled={safePage >= totalPages} onClick={() => onPageChange(totalPages)} aria-label={t('lastPage', 'Last page')}><FiChevronsRight size={14} /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DataTable;
