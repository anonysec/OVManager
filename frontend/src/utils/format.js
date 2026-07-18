// Shared display formatters.

// Unlimited-traffic sentinel used by the backend: 2^31 * 100.
// Any value at/above this is treated as "Unlimited".
const UNLIMITED_SENTINEL = 214748364800;

export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!n || n <= 0) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

// Total traffic for a user: None => —, sentinel/unlimited => Unlimited, else human bytes.
export function formatTraffic(bytes) {
  const n = Number(bytes);
  if (!n || isNaN(n)) return '—';
  if (n >= UNLIMITED_SENTINEL || n >= 2147483648) return 'Unlimited';
  return formatBytes(n);
}
