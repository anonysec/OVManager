// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/** UI preference helpers (table density, accent, …) — localStorage + event. */

const PREFIX = 'ovmanager-ui-';

export const getUiPref = (key, fallback = null) => {
  try {
    const v = localStorage.getItem(PREFIX + key);
    return v === null ? fallback : v;
  } catch { return fallback; }
};

export const setUiPref = (key, value) => {
  try {
    localStorage.setItem(PREFIX + key, String(value));
    window.dispatchEvent(new Event('ovmanager-ui-prefs'));
  } catch { /* noop */ }
};


/** Apply the persisted accent color as the --accent-color CSS variable. */
export const applyAccent = () => {
  const accent = getUiPref('accent', '');
  const root = document.documentElement;
  if (accent) {
    root.style.setProperty('--accent-color', accent);
  } else {
    root.style.removeProperty('--accent-color');
  }
};

