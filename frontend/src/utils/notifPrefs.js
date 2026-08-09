/**
 * Notification preferences utilities.
 * Stores per-node alert toggles and global dashboard refresh interval in localStorage.
 */

const PREFIX = 'ovm_notif_';
const GLOBAL_KEY = 'ovm_global';

/** Read all global preferences */
export function readPrefs() {
  try {
    const raw = localStorage.getItem(GLOBAL_KEY);
    return raw ? JSON.parse(raw) : { alertTypes: [], refreshSec: 30 };
  } catch {
    return { alertTypes: [], refreshSec: 30 };
  }
}

/** Write a single global preference */
export function writePref(key, value) {
  const prefs = readPrefs();
  prefs[key] = value;
  localStorage.setItem(GLOBAL_KEY, JSON.stringify(prefs));
}

/** Get the localStorage key for a node's alert preference */
export function alertPrefKey(nodeId) {
  return `${PREFIX}${nodeId}`;
}

/** Read alert types for a specific node */
export function readAlertTypes(nodeId) {
  try {
    const raw = localStorage.getItem(alertPrefKey(nodeId));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/** Write alert types for a specific node */
export function writeAlertTypes(nodeId, types) {
  localStorage.setItem(alertPrefKey(nodeId), JSON.stringify(types));
}

/** Dashboard refresh interval options (seconds) */
export const REFRESH_OPTIONS = [15, 30, 60, 120, 300];