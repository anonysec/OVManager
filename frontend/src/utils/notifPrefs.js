// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Front-end only (localStorage), toggled from Settings → "Alerts & Dashboard".
// Every change dispatches `ovmanager-prefs-changed` so live components (topbar
// notifications, dashboard polling) pick it up without a reload.


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

// Single cadence for dashboard, bell and node lists; deliberately not
// user-configurable, since the live stream already pushes immediacy and these
// polls are background refreshes that never flash a loading state.
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

export const alertPrefKey = (id) => {
  if (String(id).startsWith('node-')) return 'nodeDown';
  if (String(id).startsWith('full-')) return 'maxLogins';
  if (id === 'auth') return 'authErrors';
  if (id === 'rej') return 'rejects';
  if (String(id).startsWith('quota-')) return 'quota';
  return null;
};
