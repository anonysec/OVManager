// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Date/time formatting helpers shared across the app.
// Timestamps render in the operator display timezone from backend Settings
// (see displayTimezone.js) unless the caller passes { timeZone }.

import i18n from '../i18n';
import { getDisplayTimezone } from './displayTimezone';

// Display locale follows the UI language. Persian stays on the Gregorian
// calendar with Latin digits so panel dates stay comparable with the
// backend (which stores ISO Gregorian everywhere).
function displayLocale() {
  const l = (i18n.language || '').toLowerCase();
  if (l.startsWith('fa')) return 'fa-u-ca-gregory-nu-latn';
  if (l.startsWith('ru')) return 'ru';
  if (l.startsWith('zh')) return 'zh';
  return 'en-GB';
}

function safeT(key, fallback) {
  try {
    return i18n.t(key, { defaultValue: fallback }) || fallback;
  } catch {
    return fallback;
  }
}

// Format an ISO string (UTC) into the operator timezone.
export function fmtDateTime(iso, opts = {}) {
  if (!iso) return '—';
  const { timeZone = getDisplayTimezone(), ...rest } = opts;
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  try {
    return new Intl.DateTimeFormat(displayLocale(), {
      timeZone,
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      ...rest,
    }).format(d);
  } catch {
    return d.toLocaleString();
  }
}

export function fmtDate(iso, opts = {}) {
  if (!iso) return '—';
  const { timeZone = getDisplayTimezone(), ...rest } = opts;
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      ...rest,
    }).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

// Alias used by UserTable / list views.
export const formatDate = fmtDate;

// "3h ago" style relative time, localized via Intl (English fallback kept
// for environments without the ICU data).
export function fmtRelative(iso) {
  if (!iso) return safeT('never', 'never');
  const d = new Date(iso);
  if (isNaN(d)) return safeT('never', 'never');
  // Intl.RelativeTimeFormat signs past times NEGATIVE (ts - now).
  const diffMs = d.getTime() - Date.now();
  const abs = Math.abs(diffMs);
  if (abs < 30000) return safeT('justNow', 'just now');
  const lang = (i18n.language || 'en').slice(0, 2);
  try {
    const rtf = new Intl.RelativeTimeFormat(lang === 'en' ? 'en' : lang, { numeric: 'auto' });
    if (abs < 3600000) return rtf.format(Math.round(diffMs / 60000), 'minute');
    if (abs < 86400000) return rtf.format(Math.round(diffMs / 3600000), 'hour');
    if (abs < 2592000000) return rtf.format(Math.round(diffMs / 86400000), 'day');
  } catch {
    // Fall through to the English helper.
  }
  const min = Math.floor(-diffMs / 60000);
  if (min < 1) return safeT('justNow', 'just now');
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return fmtDate(iso);
}

// Days until a YYYY-MM-DD expiry date (negative = expired).
export function daysUntil(expiry) {
  if (!expiry) return Infinity;
  const d = new Date(expiry);
  if (isNaN(d)) return Infinity;
  const now = new Date();
  return Math.ceil((d - now) / 86400000);
}

// Format uptime seconds into human-readable "Xd Yh Zm"
export function formatUptime(seconds) {
  if (!seconds || seconds === '-') return '-';
  const n = Number(seconds);
  if (isNaN(n) || n < 0) return '-';
  const d = Math.floor(n / 86400);
  const h = Math.floor((n % 86400) / 3600);
  const m = Math.floor((n % 3600) / 60);
  const parts = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  if (m > 0 || parts.length === 0) parts.push(`${m}m`);
  return parts.join(' ');
}
