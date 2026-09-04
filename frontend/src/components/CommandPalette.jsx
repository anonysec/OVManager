import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiSearch, FiServer, FiUsers, FiSettings, FiUserCheck, FiFileText, FiArrowUp, FiDatabase, FiShield } from 'react-icons/fi';
import apiClient from '../services/api';
import { asList } from '../utils/apiData';

const PAGES = (t, isAdmin) => [
  { label: t('navDashboard', 'Dashboard'), path: '/', icon: FiServer, group: t('navGroupPages', 'Pages') },
  { label: t('navUsers', 'Users'), path: '/users', icon: FiUsers, group: t('navGroupPages', 'Pages') },
  { label: t('navNodes', 'Nodes'), path: '/nodes', icon: FiFileText, group: t('navGroupPages', 'Pages') },
  { label: t('navSettings', 'Settings'), path: '/settings', icon: FiSettings, group: t('navGroupPages', 'Pages') },
  ...(isAdmin ? [
    { label: t('navAdmins', 'Admins'), path: '/admins', icon: FiUserCheck, group: t('navGroupPages', 'Pages') },
    { label: t('navAudit', 'Audit Log'), path: '/audit', icon: FiShield, group: t('navGroupPages', 'Pages') },
    { label: t('navMaintenance', 'Maintenance'), path: '/maintenance', icon: FiDatabase, group: t('navGroupPages', 'Pages') },
    { label: t('addNewUser', 'Add user'), path: '/users?add=1', icon: FiUsers, group: t('navGroupPages', 'Pages') },
    { label: t('addNewNode', 'Add node'), path: '/nodes?add=1', icon: FiFileText, group: t('navGroupPages', 'Pages') },
  ] : []),
];

const CommandPalette = ({ userRole }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState([]);
  const [nodes, setNodes] = useState([]);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);

  const isAdmin = userRole === 'owner';

  // Global shortcut: Ctrl/Cmd+K. The topbar trigger emits the same event
  // so keyboard and pointer users get the exact same search experience.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener('keydown', onKey);
    window.addEventListener('ovmanager:open-palette', onOpen);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('ovmanager:open-palette', onOpen);
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const [u, n] = await Promise.all([
        apiClient.get('/users/'),
        apiClient.get('/nodes/'),
      ]);
      setUsers(asList(u.data, 'users').slice(0, 50));
      setNodes(asList(n.data, 'nodes').slice(0, 50));
    } catch { /* palette stays usable with pages only */ }
  }, []);

  useEffect(() => {
    if (open) {
      setQuery('');
      setCursor(0);
      load();
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open, load]);

  const q = query.trim().toLowerCase();
  const pages = PAGES(t, isAdmin);
  const matchedUsers = q ? users.filter((x) => (x.name || '').toLowerCase().includes(q)) : [];
  const matchedNodes = q ? nodes.filter((x) => (x.name || '').toLowerCase().includes(q)) : [];
  const matchedPages = q ? pages.filter((x) => x.label.toLowerCase().includes(q)) : pages;

  const results = [
    ...matchedPages.map((p) => ({ ...p, kind: 'page' })),
    ...matchedUsers.map((x) => ({ label: x.name, sub: t('palUser', 'User'), path: `/users?user=${x.uuid}`, icon: FiUsers, kind: 'user' })),
    ...matchedNodes.map((x) => ({ label: x.name, sub: t('palNode', 'Node'), path: `/nodes?node=${x.id}`, icon: FiFileText, kind: 'node' })),
  ];

  const go = (item) => {
    setOpen(false);
    navigate(item.path);
  };

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === 'Enter' && results[cursor]) { go(results[cursor]); }
  };

  if (!open) return null;

  return (
    <div className="palette-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label={t('palTitle', 'Command palette')}>
        <div className="palette-input-row">
          <FiSearch className="palette-search-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            className="palette-input"
            placeholder={t('palPlaceholder', 'Search pages, users, nodes…')}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setCursor(0); }}
            onKeyDown={onKeyDown}
            aria-label={t('palPlaceholder', 'Search pages, users, nodes…')}
          />
          <kbd className="palette-kbd">ESC</kbd>
        </div>
        <div className="palette-results" role="listbox" aria-label={t('palResults', 'Results')}>
          {results.length === 0 && (
            <div className="palette-empty">{t('palEmpty', 'No matches')}</div>
          )}
          {results.map((item, i) => {
            const Icon = item.icon;
            return (
              <button
                type="button"
                key={`${item.kind}-${item.label}`}
                role="option"
                aria-selected={i === cursor}
                className={`palette-item${i === cursor ? ' is-active' : ''}`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(item)}
              >
                <span className="palette-item-icon" aria-hidden="true"><Icon /></span>
                <span className="palette-item-label">
                  {item.label}
                  {item.sub && <small>{item.sub}</small>}
                </span>
                <FiArrowUp className="palette-item-go" aria-hidden="true" />
              </button>
            );
          })}
        </div>
        <div className="palette-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> {t('palNav', 'Navigate')}</span>
          <span><kbd>↵</kbd> {t('palOpen', 'Open')}</span>
          <span><kbd>esc</kbd> {t('palClose', 'Close')}</span>
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;
