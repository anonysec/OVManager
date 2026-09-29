// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Operator display timezone (IANA name, e.g. "Asia/Tehran") from backend
// Settings. Owners load it from /server/settings; everyone (including
// non-owner admins, who cannot call that owner-only endpoint) reads the
// guarded localStorage cache so dates still render in the operator zone.
//
// time.js defaults to getDisplayTimezone() — callers can still pass an
// explicit { timeZone } to override.

const STORAGE_KEY = 'ovTimezone';

function isValidZone(tz) {
  if (!tz || typeof tz !== 'string') return false;
  try {
    new Intl.DateTimeFormat('en', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

function readCached() {
  try {
    if (typeof localStorage !== 'undefined') {
      const v = localStorage.getItem(STORAGE_KEY);
      if (isValidZone(v)) return v;
    }
  } catch {
    /* blocked storage (tests without origin, privacy mode): ignore */
  }
  return 'UTC';
}

let current = readCached();

export function getDisplayTimezone() {
  return current;
}

export function setDisplayTimezone(tz) {
  if (!isValidZone(tz)) return null;
  current = tz;
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, tz);
  } catch {
    /* preference only: never break a save */
  }
  return current;
}
