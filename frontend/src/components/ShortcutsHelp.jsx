import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

const ROWS = (t, isOwner) => [
  { keys: ['g', 'd'], label: t('shortcutGoDashboard', 'Go to dashboard') },
  { keys: ['g', 'u'], label: t('shortcutGoUsers', 'Go to users') },
  { keys: ['g', 'n'], label: t('shortcutGoNodes', 'Go to nodes') },
  ...(isOwner ? [{ keys: ['g', 'a'], label: t('shortcutGoAdmins', 'Go to admins') }] : []),
  { keys: ['g', 's'], label: t('shortcutGoSettings', 'Go to settings') },
  { keys: ['/'], label: t('shortcutSearch', 'Focus search') },
  { keys: ['⌘', 'K'], label: t('shortcutPalette', 'Open command palette') },
  { keys: ['?'], label: t('shortcutHelp', 'Show this cheatsheet') },
  { keys: ['⇧', 'Q'], label: t('shortcutLogout', 'Sign out') },
];

const ShortcutsHelp = ({ open, onClose, isOwner }) => {
  const { t } = useTranslation();
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const focusTimer = setTimeout(() => ref.current?.focus(), 0);
    return () => {
      document.removeEventListener('keydown', onKey);
      clearTimeout(focusTimer);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="palette-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className="shortcuts-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        ref={ref}
        tabIndex={-1}
      >
        <div className="shortcuts-head">
          <h2 id="shortcuts-title">{t('shortcutsTitle', 'Keyboard shortcuts')}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label={t('palClose', 'Close')}>×</button>
        </div>
        <p className="shortcuts-hint">{t('shortcutsHint', 'Type these anywhere except inside a field.')}</p>
        <ul className="shortcuts-list">
          {ROWS(t, isOwner).map((row) => (
            <li key={row.label}>
              <span>{row.label}</span>
              <span className="shortcuts-keys">
                {row.keys.map((k) => <kbd key={k}>{k}</kbd>)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default ShortcutsHelp;
