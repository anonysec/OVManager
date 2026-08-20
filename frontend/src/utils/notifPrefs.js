// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * User preference helpers for dashboard alerts and polling.
 *
 * All prefs are front-end only (localStorage) — nothing sensitive here.
 * Toggled from Settings → "Alerts & Dashboard". Every change dispatches
 * `ovmanager-prefs-changed` so live components (topbar notifications,
 * dashboard polling) pick it up without a reload.
 */

const KEYS = {
  nodeDown: 'ovmanager-pref-alert-node',
  maxLogins: 'ovmanager-pref-alert-maxlogin',
  authErrors: 'ovmanager-pref-alert-auth',
  rejects: 'ovmanager-pref-alert-reject',
  stale: 'ovmanager-pref-alert-stale',
  refreshSec: 'ovmanager-pref-refresh',
};

const DEFAULTS = {
  nodeDown: true,
  maxLogins: true,
  authErrors: true,
  rejects: true,
  stale: true,
  refreshSec: 30,
};

export const REFRESH_OPTIONS = [15, 30, 60, 300];

export const readPrefs = () => {
  const out = { ...DEFAULTS };
  try {
    for (const [key, storageKey] of Object.entries(KEYS)) {
      const raw = localStorage.getItem(storageKey);
      if (raw === null) continue;
      if (key === 'refreshSec') {
        out[key] = REFRESH_OPTIONS.includes(Number(raw)) ? Number(raw) : DEFAULTS.refreshSec;
      } else {
        out[key] = raw === 'true';
      }
    }
  } catch { /* storage unavailable — use defaults */ }
  return out;
};

export const writePref = (key, value) => {
  try {
    localStorage.setItem(KEYS[key], String(value));
    window.dispatchEvent(new Event('ovmanager-prefs-changed'));
  } catch { /* noop */ }
};

/** Alert-type → preference key map used to filter notification lists. */
export const alertPrefKey = (id) => {
  if (String(id).startsWith('node-')) return 'nodeDown';
  if (String(id).startsWith('full-')) return 'maxLogins';
  if (id === 'auth') return 'authErrors';
  if (id === 'rej') return 'rejects';
  if (id === 'stale') return 'stale';
  return null;
};
