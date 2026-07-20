import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { FiEdit2, FiTrash2, FiMoreVertical, FiChevronUp, FiChevronDown, FiCopy, FiActivity, FiDownload, FiUserX, FiUserCheck } from 'react-icons/fi';
import { daysUntil, formatDate } from '../utils/time';
import { formatTraffic } from '../utils/format';
import { copyText } from '../utils/clipboard';

const statusOf = (user, t) => {
  const online = user.online || Number(user.active_connections || 0) > 0;
  if (online) return { label: t('statusOnline'), cls: 'online' };
  const d = daysUntil(user.expiry_date);
  if (d < 0) return { label: t('expired'), cls: 'expired' };
  if (user.is_active === false) return { label: t('disabled'), cls: 'offline' };
  return { label: t('statusOffline'), cls: 'idle' };
};

const RowMenu = ({ user, onEdit, onDelete, onSessions, onDownload, onToggleStatus, onClose, anchorRef }) => {
  const { t } = useTranslation();
  const ref = useRef(null);
  const [pos, setPos] = useState({ top: 0, left: 0, ready: false });
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const place = () => {
      const a = anchorRef?.current;
      if (!a) return;
      const r = a.getBoundingClientRect();
      const menuW = 180;
      const menuH = 184;
      let left = r.right - menuW;
      let top = r.bottom + 6;
      if (left < 8) left = 8;
      if (top + menuH > window.innerHeight - 8) top = r.top - menuH - 6;
      setPos({ top, left, ready: true });
    };
    place();
    const onScroll = () => onClose();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [anchorRef, onClose]);

  useEffect(() => {
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target) && anchorRef?.current && !anchorRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [onClose, anchorRef]);

  return createPortal(
    <div
      className="row-menu"
      ref={ref}
      role="menu"
      style={{ position: 'fixed', top: pos.top, left: pos.left, visibility: pos.ready ? 'visible' : 'hidden' }}
    >
      <button type="button" className="row-menu-item" role="menuitem" onClick={() => { onEdit(user); onClose(); }}><FiEdit2 /> {t('rowEdit')}</button>
      <button type="button" className="row-menu-item" role="menuitem" onClick={() => { onSessions?.(user); onClose(); }}><FiActivity /> {t('rowSessions')}</button>
      <button type="button" className="row-menu-item" role="menuitem" onClick={async () => { await copyText(user.uuid || ''); setCopied(true); setTimeout(() => setCopied(false), 1400); }}><FiCopy /> {copied ? t('copied') : t('copyId')}</button>
      <button type="button" className="row-menu-item" role="menuitem" onClick={() => { onDownload?.(user); onClose(); }}><FiDownload /> {t('downloadConfig')}</button>
      <button type="button" className={`row-menu-item ${user.is_active ? '' : 'danger'}`} role="menuitem" onClick={() => { onToggleStatus?.(user); onClose(); }}>{user.is_active ? <FiUserX /> : <FiUserCheck />} {user.is_active ? t('disableUser') : t('enableUser')}</button>
      <button type="button" className="row-menu-item danger" role="menuitem" onClick={() => { onDelete(user); onClose(); }}><FiTrash2 /> {t('rowDelete')}</button>
    </div>,
    document.body
  );
};

const UserTable = ({
  users = [],
  isLoading = false,
  onUserClick,
  onEdit,
  onDelete,
  onSessions,
  onDownload,
  onToggleStatus,
  onBulkDelete,
  selected = [],
  onSelect,
  onSelectAll,
  sort,
  onSort,
}) => {
  const { t } = useTranslation();
  const allSelected = users.length > 0 && selected.length === users.length;
  const someSelected = selected.length > 0 && !allSelected;
  const [menuFor, setMenuFor] = useState(null);
  const anchorRefs = useRef({});

  if (isLoading) {
    return <div className="table-skeleton">{t('loading')}</div>;
  }

  if (!users.length) {
    return (
      <div className="empty-state">
        <div className="empty-illustration" aria-hidden="true">
          <svg viewBox="0 0 120 120" width="120" height="120">
            <circle cx="60" cy="60" r="54" fill="none" stroke="var(--line)" strokeWidth="2" />
            <circle cx="46" cy="50" r="16" fill="none" stroke="var(--orange)" strokeWidth="3" />
            <path d="M24 96c0-14 12-22 26-22s26 8 26 22" fill="none" stroke="var(--orange)" strokeWidth="3" />
            <line x1="78" y1="74" x2="100" y2="96" stroke="var(--orange)" strokeWidth="3" strokeLinecap="round" />
            <circle cx="88" cy="86" r="9" fill="var(--panel)" stroke="var(--orange)" strokeWidth="3" />
          </svg>
        </div>
        <h3>{t('noUsersTitle')}</h3>
        <p>{t('noUsersBody')}</p>
      </div>
    );
  }

  return (
    <>
      {selected.length > 0 && (
        <div className="bulk-bar">
          <span className="bulk-count">{selected.length} {t('selected')}</span>
          <button className="btn btn-danger btn-sm" onClick={() => onBulkDelete(selected)}>
            <FiTrash2 /> {t('deleteSelected')}
          </button>
          <button className="btn btn-sm" onClick={() => onSelectAll(false)}>{t('clear')}</button>
        </div>
      )}
      <div className="list-table-container">
        <table className="list-table user-list-table">
          <thead>
            <tr>
              <th className="col-check">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => { if (el) el.indeterminate = someSelected; }}
                  onChange={(e) => onSelectAll(e.target.checked)}
                  aria-label="Select all users"
                />
              </th>
              <th className={sort.key === 'name' ? 'sortable active' : 'sortable'} onClick={() => onSort('name')}>{t('th_username')}{sort.key === 'name' && (sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />)}</th>
              <th>{t('th_status')}</th>
              <th className={sort.key === 'expiry_date' ? 'sortable active' : 'sortable'} onClick={() => onSort('expiry_date')}>{t('th_expiryDate')}{sort.key === 'expiry_date' && (sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />)}</th>
              <th className={sort.key === 'total' ? 'sortable active' : 'sortable'} onClick={() => onSort('total')}>{t('th_totalTraffic')}{sort.key === 'total' && (sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />)}</th>
              <th className={sort.key === 'max_logins' ? 'sortable active' : 'sortable'} onClick={() => onSort('max_logins')}>{t('th_maxLogins')}{sort.key === 'max_logins' && (sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />)}</th>
              <th className={sort.key === 'last_online' ? 'sortable active' : 'sortable'} onClick={() => onSort('last_online')}>{t('th_lastOnline')}{sort.key === 'last_online' && (sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />)}</th>
              <th className={sort.key === 'owner' ? 'sortable active' : 'sortable'} onClick={() => onSort('owner')}>{t('th_owner')}{sort.key === 'owner' && (sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />)}</th>
              <th>{t('th_actions')}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const isSel = selected.includes(user.uuid);
              const d = daysUntil(user.expiry_date);
              const st = statusOf(user, t);
              const open = menuFor === user.uuid;
              return (
                <tr key={user.uuid} className={isSel ? 'selected' : ''}>
                  <td className="col-check">
                    <input type="checkbox" checked={isSel} onChange={() => onSelect(user.uuid)} aria-label={`Select ${user.name}`} />
                  </td>
                  <td data-label="Username">
                    <div className="user-cell user-cell-clickable" onClick={(e) => { e.stopPropagation(); onUserClick?.(user); }}>
                      <span className="avatar-sm">{user.name.slice(0, 1).toUpperCase()}</span>
                      <span className="uname">{user.name}</span>
                    </div>
                  </td>
                  <td data-label="Status"><span className={`status-pill ${st.cls}`}>{st.label}</span></td>
                  <td data-label="Expiry Date"><span className={d >= 0 && d <= 7 ? 'expiry-soon' : ''}>{formatDate(user.expiry_date)}</span></td>
                  <td data-label="Total Traffic" className="traffic-cell">
                    <span className="traffic-used">{formatTraffic(user.used)}</span>
                    <span className="traffic-limit">/ {Number(user.total) > 0 ? formatTraffic(user.total) : '∞'}</span>
                  </td>
                  <td data-label="Max Logins"><span className="login-badge">{user.active_connections ?? 0}/{user.max_logins ?? 0}</span></td>
                  <td data-label="Last Online">{user.last_online ? formatDate(user.last_online) : t('never')}</td>
                  <td data-label="Owner">{user.owner || '—'}</td>
                  <td data-label="Actions" className="actions-cell">
                    <button className="icon-btn" onClick={() => onEdit(user)} title="Edit"><FiEdit2 /></button>
                    <button className="icon-btn danger" onClick={() => onDelete(user)} title="Delete"><FiTrash2 /></button>
                    <div className="row-menu-wrap">
                      <button
                        className="icon-btn"
                        title="More"
                        ref={(el) => { anchorRefs.current[user.uuid] = el; }}
                        onClick={() => setMenuFor(open ? null : user.uuid)}
                        aria-haspopup="menu"
                        aria-expanded={open}
                      ><FiMoreVertical /></button>
                      {open && (
                        <RowMenu
                          user={user}
                          anchorRef={{ current: anchorRefs.current[user.uuid] }}
                          onEdit={onEdit}
                          onDelete={onDelete}
                          onSessions={onSessions}
                          onDownload={onDownload}
                          onToggleStatus={onToggleStatus}
                          onClose={() => setMenuFor(null)}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
};

export default UserTable;
