// Timezone-aware formatting helpers shared across the app.
// The operator timezone is persisted in the backend Settings (timezone field)
// and mirrored to localStorage for instant use before the settings load.

const STORAGE_KEY = 'ovTimezone';

export function getTimezone() {
  return localStorage.getItem(STORAGE_KEY) || 'UTC';
}

export function setTimezone(tz) {
  if (tz) localStorage.setItem(STORAGE_KEY, tz);
}

// Format an ISO string (UTC) into the operator timezone.
export function fmtDateTime(iso, opts = {}) {
  if (!iso) return '—';
  const tz = getTimezone();
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: tz,
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      ...opts,
    }).format(d);
  } catch {
    return d.toLocaleString();
  }
}

export function fmtDate(iso, opts = {}) {
  if (!iso) return '—';
  const tz = getTimezone();
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      ...opts,
    }).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

// Alias used by UserTable / list views.
export const formatDate = fmtDate;

// "3h ago" style relative time from an ISO string.
export function fmtRelative(iso) {
  if (!iso) return 'never';
  const d = new Date(iso);
  if (isNaN(d)) return 'never';
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return 'just now';
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
