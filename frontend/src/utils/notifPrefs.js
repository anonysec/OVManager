// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

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
  quota: 'ovmanager-pref-alert-quota',
};

const DEFAULTS = {
  nodeDown: true,
  maxLogins: true,
  authErrors: true,
  rejects: true,
  quota: true,
};

// Single polling cadence for dashboard, bell and node lists. There is no
// user-facing refresh setting: the live stream (or its tick fallback)
// already pushes immediacy, and every poll below is a background refresh
// that never flashes loading states.
export const DATA_REFRESH_SEC = 30;

export const readPrefs = () => {
  const out = { ...DEFAULTS };
  try {
    for (const [key, storageKey] of Object.entries(KEYS)) {
      const raw = localStorage.getItem(storageKey);
      if (raw === null) continue;
      out[key] = raw === 'true';
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
  if (String(id).startsWith('quota-')) return 'quota';
  return null;
};
