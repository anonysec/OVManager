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


/** Panel visual style: 'normal' (rich cards) or 'minimal' (flat, hairline).
    Stored per browser; applied as data-ui-style on <html> so the whole
    stylesheet can react without touching every component. */
export const getUiStyle = () => getUiPref('style', 'normal');

export const applyUiStyle = () => {
  const style = getUiStyle();
  const root = document.documentElement;
  if (style === 'minimal') {
    root.setAttribute('data-ui-style', 'minimal');
  } else {
    root.removeAttribute('data-ui-style');
  }
};

export const setUiStyle = (style) => {
  setUiPref('style', style);
  applyUiStyle();
};

