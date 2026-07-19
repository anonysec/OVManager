// Shared display formatters.

export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!n || n <= 0) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

// Total traffic for a user. Bytes in, human out. None/0 => dash.
// (Backend stores the limit in bytes; 200GB => 214748364800, NOT unlimited.)
export function formatTraffic(bytes) {
  const n = Number(bytes);
  if (!n || isNaN(n)) return '—';
  return formatBytes(n);
}
