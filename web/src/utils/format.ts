// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

export function formatBytes(bytes: number | string | null | undefined): string {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  // A synthetic axis tick can be a fraction of a byte (half of a 1 B peak);
  // without this guard the index goes negative and the unit is undefined.
  if (n < 1) return `${n.toFixed(1)} B`;
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}
