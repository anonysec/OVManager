import React, { useState, useRef, useEffect } from 'react';
import { FiEdit2, FiTrash2, FiMoreVertical, FiChevronUp, FiChevronDown, FiUserX, FiCopy, FiActivity } from 'react-icons/fi';
import { daysUntil, formatDate } from '../utils/time';
import { formatTraffic } from '../utils/format';

const COLUMNS = [
  { key: 'name', label: 'Username', sortable: true },
  { key: 'status', label: 'Status', sortable: false },
  { key: 'expiry_date', label: 'Expiry Date', sortable: true },
  { key: 'total', label: 'Total Traffic', sortable: true },
  { key: 'max_logins', label: 'Max Logins', sortable: true },
  { key: 'last_online', label: 'Last Online', sortable: true },
  { key: 'owner', label: 'Owner', sortable: true },
  { key: 'actions', label: 'Actions', sortable: false },
];

const statusOf = (user) => {
  const online = user.online || Number(user.active_connections || 0) > 0;
  if (online) return { label: 'Online', cls: 'online' };
  const d = daysUntil(user.expiry_date);
  if (d < 0) return { label: 'Expired', cls: 'expired' };
  if (user.is_active === false) return { label: 'Disabled', cls: 'offline' };
  return { label: 'Offline', cls: 'idle' };
};

const RowMenu = ({ user, onEdit, onDelete, onSessions, onClose, anchorRef }) => {
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target) && anchorRef?.current && !anchorRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [onClose, anchorRef]);
  return (
    <div className="row-menu" ref={ref} role="menu">
      <button type="button" className="row-menu-item" role="menuitem" onClick={() => { onEdit(user); onClose(); }}><FiEdit2 /> Edit</button>
      <button type="button" className="row-menu-item" role="menuitem" onClick={() => { onSessions?.(user); onClose(); }}><FiActivity /> Sessions</button>
      <button type="button" className="row-menu-item" role="menuitem" onClick={() => { navigator.clipboard?.writeText(user.uuid || ''); onClose(); }}><FiCopy /> Copy ID</button>
      <button type="button" className="row-menu-item danger" role="menuitem" onClick={() => { onDelete(user); onClose(); }}><FiTrash2 /> Delete</button>
    </div>
  );
};

const UserTable = ({
  users = [],
  isLoading = false,
  onEdit,
  onDelete,
  onSessions,
  onBulkDelete,
  selected = [],
  onSelect,
  onSelectAll,
  sort,
  onSort,
}) => {
  const allSelected = users.length > 0 && selected.length === users.length;
  const someSelected = selected.length > 0 && !allSelected;
  const [menuFor, setMenuFor] = useState(null);
  const anchorRefs = useRef({});

  if (isLoading) {
    return <div className="table-skeleton">Loading users…</div>;
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
        <h3>No users yet</h3>
        <p>Create a user to start handing out VPN access. They'll appear here with live status.</p>
      </div>
    );
  }

  return (
    <>
      {selected.length > 0 && (
        <div className="bulk-bar">
          <span className="bulk-count">{selected.length} selected</span>
          <button className="btn btn-danger btn-sm" onClick={() => onBulkDelete(selected)}>
            <FiTrash2 /> Delete selected
          </button>
          <button className="btn btn-sm" onClick={() => onSelectAll(false)}>Clear</button>
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
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={col.sortable ? 'sortable' : ''}
                  onClick={col.sortable ? () => onSort(col.key) : undefined}
                >
                  {col.label}
                  {col.sortable && sort.key === col.key && (
                    sort.dir === 'asc' ? <FiChevronUp className="sort-ic" /> : <FiChevronDown className="sort-ic" />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const isSel = selected.includes(user.uuid);
              const d = daysUntil(user.expiry_date);
              const st = statusOf(user);
              const open = menuFor === user.uuid;
              return (
                <tr key={user.uuid} className={isSel ? 'selected' : ''}>
                  <td className="col-check">
                    <input
                      type="checkbox"
                      checked={isSel}
                      onChange={() => onSelect(user.uuid)}
                      aria-label={`Select ${user.name}`}
                    />
                  </td>
                  <td data-label="Username">
                    <div className="user-cell">
                      <span className="avatar-sm">{user.name.slice(0, 1).toUpperCase()}</span>
                      <span className="uname">{user.name}</span>
                    </div>
                  </td>
                  <td data-label="Status">
                    <span className={`status-pill ${st.cls}`}>{st.label}</span>
                  </td>
                  <td data-label="Expiry Date">
                    <span className={d >= 0 && d <= 7 ? 'expiry-soon' : ''}>{formatDate(user.expiry_date)}</span>
                  </td>
                  <td data-label="Total Traffic" className="traffic-cell">{formatTraffic(user.total)}</td>
                  <td data-label="Max Logins">
                    <span className="login-badge">{user.active_connections ?? 0}/{user.max_logins ?? 0}</span>
                  </td>
                  <td data-label="Last Online">{user.last_online ? formatDate(user.last_online) : 'never'}</td>
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
