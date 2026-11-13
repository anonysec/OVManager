// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT



const KEYS: Record<string, string> = {
  nodeDown: 'ovmanager-pref-alert-node',
  authErrors: 'ovmanager-pref-alert-auth',
  quota: 'ovmanager-pref-alert-quota',
};

const DEFAULTS = {
  nodeDown: true,
  authErrors: true,
  quota: true,
};

export const DATA_REFRESH_SEC = 30;

export const readPrefs = (): Record<string, boolean> => {
  const out: Record<string, boolean> = { ...DEFAULTS };
  try {
    for (const [key, storageKey] of Object.entries(KEYS)) {
      const raw = localStorage.getItem(storageKey);
      if (raw === null) continue;
      out[key] = raw === 'true';
    }
  } catch { /* storage unavailable — use defaults */ }
  return out;
};

export const writePref = (key: string, value: unknown): void => {
  const storageKey = KEYS[key];
  if (!storageKey) return;
  try {
    localStorage.setItem(storageKey, String(value));
    window.dispatchEvent(new Event('ovmanager-prefs-changed'));
  } catch { /* noop */ }
};

export const alertPrefKey = (id: string | number): string | null => {
  if (String(id).startsWith('node-')) return 'nodeDown';
  if (id === 'auth') return 'authErrors';
  if (String(id).startsWith('quota-')) return 'quota';
  return null;
};
