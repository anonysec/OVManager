import React, { useState, useRef, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import StatusBadge from '../components/ui/StatusBadge';
import EmptyState from '../components/ui/EmptyState';
import { FiEdit2, FiTrash2, FiMoreVertical, FiChevronUp, FiChevronDown, FiCopy, FiActivity, FiDownload, FiUserX, FiUserCheck, FiChevronsUp, FiChevronLeft, FiChevronRight, FiLink, FiClock, FiPower, FiCheck } from 'react-icons/fi';
import { daysUntil, formatDate } from '../utils/time';
import { formatTraffic } from '../utils/format';
import { copyText } from '../utils/clipboard';

const statusOf = (user, t) => {
  const online = user.online || Number(user.active_connections || 0) > 0;
  if (online) return { label: t('statusOnline'), status: 'online' };
  const d = daysUntil(user.expiry_date);
  if (d < 0) return { label: t('expired'), status: 'warning' };
  if (user.is_active === false) return { label: t('disabled'), status: 'offline' };
  return { label: t('statusOffline'), status: 'idle' };
};

const RowMenu = ({ user, onEdit, onDelete, onSessions, onDownload, onToggleStatus, onClose, anchorRefs, onCopyLink, onShowQR, onExtend, onDisconnect }) => {
  const { t } = useTranslation();
  const ref = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0, ready: false });
  const [copied, setCopied] = useState(false);

  // Measure the REAL rendered menu size and place it so it never overflows the viewport.
  // (Previously used a hardcoded 184px height guess that broke with longer
  // translations and small screens.) Runs twice: once before paint via rAF,
  // then again after layout settles so fonts/wrapping are taken into account.
  useEffect(() => {
    const place = () => {
      const a = anchorRefs?.current?.[user.uuid];
      const menu = ref.current;
      if (!a || !menu) return;
      const r = a.getBoundingClientRect();
      const menuW = menu.offsetWidth;
      const menuH = menu.offsetHeight;
      const MARGIN = 8;
      const GAP = 6;
      let left = r.right - menuW;
      let top = r.bottom + GAP;
      if (left < MARGIN) left = MARGIN;
      if (left + menuW > window.innerWidth - MARGIN) left = window.innerWidth - menuW - MARGIN;
      if (top + menuH > window.innerHeight - MARGIN) {
        // Flip above the anchor; if still too tall, CSS max-height + scroll takes over
        top = r.top - menuH - GAP;
        if (top < MARGIN) top = MARGIN;
      }
      setPos({ top, left, ready: true });
    };
    const raf = requestAnimationFrame(place);
    const raf2 = requestAnimationFrame(place);
    const onScroll = () => onClose();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      cancelAnimationFrame(raf);
      cancelAnimationFrame(raf2);
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [anchorRefs, user.uuid, onClose]);

  useEffect(() => {
    const trigger = anchorRefs?.current?.[user.uuid];
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target) && trigger && !trigger.contains(e.target)) {
        onClose();
      }
    };
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    // Move focus into the menu so keyboard users can operate it
    const focusTimer = setTimeout(() => ref.current?.querySelector?.('button')?.focus(), 0);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
      clearTimeout(focusTimer);
      // Return focus to the trigger button on close
      trigger?.focus?.();
    };
  }, [onClose, anchorRefs, user.uuid]);

  return createPortal(
    <div
      className="row-menu"
      ref={ref}
      role="menu"
      style={{ position: 'fixed', top: pos.top, left: pos.left, visibility: pos.ready ? 'visible' : 'hidden' }}
    >
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('rowEditAria', 'Edit {{name}}', { name: user.name })} onClick={() => { onEdit(user); onClose(); }}><FiEdit2 /> {t('rowEdit')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('copyLinkAria', 'Copy subscription link for {{name}}', { name: user.name })} onClick={async () => { await onCopyLink?.(user); setCopied(true); setTimeout(() => setCopied(false), 1400); }}><FiLink /> {copied ? <><FiCheck /> {t('copied')}</> : t('copyLink', 'Copy subscription link')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('showQRAria', 'Show QR for {{name}}', { name: user.name })} onClick={() => { onShowQR?.(user); onClose(); }}><FiActivity /> {t('showQR', 'Show QR')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('extendAria', 'Extend {{name}}', { name: user.name })} onClick={() => { onExtend?.(user); onClose(); }}><FiClock /> {t('extend30d', 'Extend +30 days')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('disconnectAria', 'Disconnect {{name}}', { name: user.name })} onClick={() => { onDisconnect?.(user); onClose(); }}><FiPower /> {t('disconnect', 'Disconnect')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('sessionsAria', 'View sessions for {{name}}', { name: user.name })} onClick={() => { onSessions?.(user); onClose(); }}><FiActivity /> {t('rowSessions')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('copyIdAria', 'Copy user ID for {{name}}', { name: user.name })} onClick={async () => { await copyText(user.uuid || ''); setCopied(true); setTimeout(() => setCopied(false), 1400); }}><FiCopy /> {copied ? t('copied') : t('copyId')}</button>
      <button type="button" className="row-menu-item" role="menuitem" aria-label={t('downloadAria', 'Download config for {{name}}', { name: user.name })} onClick={() => { onDownload?.(user); onClose(); }}><FiDownload /> {t('downloadConfig')}</button>
      <button type="button" className={`row-menu-item ${user.is_active ? '' : 'danger'}`} role="menuitem" aria-label={user.is_active ? t('disableAria', 'Disable {{name}}', { name: user.name }) : t('enableAria', 'Enable {{name}}', { name: user.name })} onClick={() => { onToggleStatus?.(user); onClose(); }}>{user.is_active ? <FiUserX /> : <FiUserCheck />} {user.is_active ? t('disableUser') : t('enableUser')}</button>
      <button type="button" className="row-menu-item danger" role="menuitem" aria-label={t('deleteAria', 'Delete {{name}}', { name: user.name })} onClick={() => { onDelete(user); onClose(); }}><FiTrash2 /> {t('rowDelete')}</button>
    </div>,
    document.body
  );
};

const UserTableSkeleton = () => {
  return (
    <div className="table-skeleton">
      <div className="skeleton-header">
        {[...Array(8)].map((_, i) => <div key={i} className="sk-line sk-header" style={{ width: i === 7 ? '20%' : '40%' }} />)}
      </div>
      {[...Array(5)].map((_, i) => (
        <div key={i} className="skeleton-row">
          {[...Array(8)].map((_, j) => <div key={j} className="sk-line" style={{ width: j === 7 ? '20%' : j === 0 ? '60%' : '30%' }} />)}
        </div>
      ))}
    </div>
  );
};

const UsageMeter = ({ used, total }) => {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const r = 11, c = 2 * Math.PI * r;
  const color = pct > 85 ? 'var(--danger-color)' : pct > 60 ? 'var(--accent-color)' : 'var(--success-color)';
  return (
    <span className="usage-meter" role="img" aria-label={`${Math.round(pct)}% used`}>
      <svg width="30" height="30">
        <circle cx="15" cy="15" r={r} fill="none" stroke="#2a3039" strokeWidth="3" />
        <circle cx="15" cy="15" r={r} fill="none" stroke={color} strokeWidth="3"
          strokeDasharray={c} strokeDashoffset={c - (pct / 100) * c} strokeLinecap="round" transform="rotate(-90 15 15)" />
      </svg>
      <b style={{ color }}>{Math.round(pct)}%</b>
    </span>
  );
};

/**
 * Sortable column header.
 *
 * Was a bare `<th onClick>`: not reachable by keyboard, and screen readers got
 * no indication a column was sorted or in which direction. The inner <button>
 * restores tab/Enter/Space for free, and aria-sort exposes the current state.
 */
const SortableTh = ({ sortKey, label, sort, onSort }) => {
  const active = sort.key === sortKey;
  const dir = active ? sort.dir : null;
  return (
    <th
      className={active ? 'sortable active' : 'sortable'}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button type="button" className="th-sort-btn" onClick={() => onSort(sortKey)}>
        <span className="th-label">{label}</span>
        <span className={`sort-indicator ${active ? `is-${dir}` : 'is-idle'}`} aria-hidden="true">
          {active ? (dir === 'asc' ? <FiChevronUp /> : <FiChevronDown />) : <FiChevronsUp />}
        </span>
      </button>
    </th>
  );
};

const PAGE_SIZE_OPTIONS = [25, 50, 100];

const UserTable = ({
  users = [],
  isLoading = false,
  onUserClick,
  onEdit,
  onDelete,
  onSessions,
  onDownload,
  onToggleStatus,
  sort,
  onSort,
  onCopyLink,
  onShowQR,
  onExtend,
  onDisconnect,
  density = 'comfortable',
  resetKey = '',
}) => {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => {
    const stored = Number(localStorage.getItem('ovmanager-ui-page-size'));
    return PAGE_SIZE_OPTIONS.includes(stored) ? stored : 25;
  });
  const [menuFor, setMenuFor] = useState(null);
  const anchorRefs = useRef({});

  const totalPages = Math.ceil(users.length / pageSize) || 1;
  const paginatedUsers = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return users.slice(start, start + pageSize);
  }, [users, currentPage, pageSize]);

  // Reset to page 1 when the operator changes the filter/search, not on
  // every SSE refresh — that used to yank people back from page 6 every 30s.
  useEffect(() => {
    setCurrentPage(1);
  }, [resetKey]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  const applyPageSize = (n) => {
    setPageSize(n);
    localStorage.setItem('ovmanager-ui-page-size', String(n));
    setCurrentPage(1);
  };

  const rangeFrom = users.length === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const rangeTo = Math.min(currentPage * pageSize, users.length);

  if (isLoading) {
    return <UserTableSkeleton />;
  }

  if (!users.length) {
    return <EmptyState title={t('noUsersTitle')} description={t('noUsersBody')} />;
  }

  return (
    <>
      <div className={`list-table-container${density === 'compact' ? ' table-compact' : ''}`}>
        <table className="list-table user-list-table">
          <thead>
            <tr>
              <SortableTh sortKey='name' label={t('th_username')} sort={sort} onSort={onSort} />
              <th>{t('th_status')}</th>
              <SortableTh sortKey='expiry_date' label={t('th_expiryDate')} sort={sort} onSort={onSort} />
              <SortableTh sortKey='total' label={t('th_totalTraffic')} sort={sort} onSort={onSort} />
              <SortableTh sortKey='max_logins' label={t('th_maxLogins')} sort={sort} onSort={onSort} />
              <SortableTh sortKey='last_online' label={t('th_lastOnline')} sort={sort} onSort={onSort} />
              <SortableTh sortKey='owner' label={t('th_owner')} sort={sort} onSort={onSort} />
              <th>{t('th_actions')}</th>
            </tr>
          </thead>
          <tbody>
            {paginatedUsers.map((user) => {
              const d = daysUntil(user.expiry_date);
              const st = statusOf(user, t);
              const open = menuFor === user.uuid;
              return (
                <tr key={user.uuid}>
                  <td data-label="Username">
                    <div className="user-cell user-cell-clickable" onClick={(e) => { e.stopPropagation(); onUserClick?.(user); }}>
                      <span className="avatar-sm">{user.name.slice(0, 1).toUpperCase()}</span>
                      <span className="uname">{user.name}</span>
                    </div>
                  </td>
                  <td data-label="Status"><StatusBadge status={st.status} label={st.label} /></td>
                  <td data-label="Expiry Date">
                    <span
                      className={`expiry-chip ${d < 0 ? 'is-expired' : d <= 7 ? 'is-soon' : 'is-ok'}`}
                      title={d < 0 ? t('expiredAgo', { days: Math.abs(d) }) : t('expiresIn', { days: d })}
                    >
                      {formatDate(user.expiry_date)}
                    </span>
                  </td>
                  <td data-label="Total Traffic" className="traffic-cell">
                    {Number(user.total) > 0 ? (
                      <>
                        <UsageMeter used={Number(user.used) || 0} total={Number(user.total)} />
                        <span className="traffic-used">{formatTraffic(user.used)}</span>
                        <span className="traffic-limit">/ {formatTraffic(user.total)}</span>
                      </>
                    ) : (
                      // Unlimited. The previous layout stacked a 30x30 ring + "—" + "∞" on
                      // the same row, which read as three competing facts. We now show a
                      // single ringless chip + the formatted used value + a soft "Unlimited"
                      // label — matches the filter chip copy so the column is self-explanatory.
                      <>
                        <span className="usage-meter usage-meter--unlimited" aria-hidden="true">
                          <svg width="30" height="30">
                            <circle cx="15" cy="15" r="11" fill="none" stroke="currentColor" strokeOpacity=".18" strokeWidth="3" />
                          </svg>
                          <b>∞</b>
                        </span>
                        <span className="traffic-used">{formatTraffic(user.used)}</span>
                        <span className="traffic-limit">{t('unlimited', 'Unlimited')}</span>
                      </>
                    )}
                  </td>
                  <td data-label="Max Logins"><span className="login-badge">{user.active_connections ?? 0}/{user.max_logins ?? 0}</span></td>
                  <td data-label="Last Online">{user.last_online ? formatDate(user.last_online) : <span className="value-muted">{t('never')}</span>}</td>
                  <td data-label="Owner">{user.owner || <span className="value-muted">—</span>}</td>
                  <td data-label="Actions" className="actions-cell">
                    <div className="row-actions">
                    <button className="icon-btn" onClick={() => onEdit(user)} title={t('edit')} aria-label={t('rowEditAria', 'Edit {{name}}', { name: user.name })}><FiEdit2 /></button>
                    <button className="icon-btn danger" onClick={() => onDelete(user)} title={t('delete')} aria-label={t('deleteAria', 'Delete {{name}}', { name: user.name })}><FiTrash2 /></button>
                    <div className="row-menu-wrap">
                      <button
                        className="icon-btn"
                        title={t('moreActions', 'More')}
                        aria-label={t('moreActionsAria', 'More actions for {{name}}', { name: user.name })}
                        ref={(el) => { anchorRefs.current[user.uuid] = el; }}
                        onClick={() => setMenuFor(open ? null : user.uuid)}
                        aria-haspopup="menu"
                        aria-expanded={open}
                      ><FiMoreVertical /></button>
                      {open && (
                        <RowMenu
                          user={user}
                          anchorRefs={anchorRefs}
                          onEdit={onEdit}
                          onDelete={onDelete}
                          onSessions={onSessions}
                          onDownload={onDownload}
                          onCopyLink={onCopyLink}
                          onShowQR={onShowQR}
                          onExtend={onExtend}
                          onDisconnect={onDisconnect}
                          onToggleStatus={onToggleStatus}
                          onClose={() => setMenuFor(null)}
                        />
                      )}
                    </div>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="pagination-controls">
        <span className="pagination-range">
          {t('showingRange', 'Showing {{from}}–{{to}} of {{total}}', { from: rangeFrom, to: rangeTo, total: users.length })}
        </span>
        <label className="page-size">
          <span>{t('rowsPerPage', 'Rows per page')}</span>
          <select
            value={pageSize}
            onChange={(e) => applyPageSize(Number(e.target.value))}
            aria-label={t('rowsPerPage', 'Rows per page')}
          >
            {PAGE_SIZE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
          >
            <FiChevronLeft size={14} /> {t('prev', 'Previous')}
          </button>
          <span className="pagination-info">
            {/* Interpolation key must match the catalogue: all four locales
                use {{page}}, so passing `current` left "{{page}}" on screen. */}
            {t('pageOf', 'Page {{page}} of {{total}}', { page: currentPage, total: totalPages })}
          </span>
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
          >
            {t('next', 'Next')} <FiChevronRight size={14} />
          </button>
        </div>
    </>
  );
};

export default UserTable;