// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

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


export const applyAccent = () => {
  const accent = getUiPref('accent', '');
  const root = document.documentElement;
  if (accent) {
    root.style.setProperty('--accent-color', accent);
  } else {
    root.style.removeProperty('--accent-color');
  }
};

