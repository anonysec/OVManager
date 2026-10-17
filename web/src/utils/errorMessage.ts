// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * FastAPI 422 bodies carry `detail: [{ loc, msg, type }]` — an ARRAY. Anything
 * that stores `data.detail` verbatim in renderable state blows up React with
 * "Objects are not valid as a React child". Normalize to a plain string here.
 */

const str = (v: unknown): string | undefined => (typeof v === 'string' && v ? v : undefined);

/** Normalize one `detail` value: array → join msgs, object → JSON, string → as-is. */
export function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => str(d?.msg) ?? JSON.stringify(d))
      .filter(Boolean)
      .join(', ');
  }
  if (detail !== null && typeof detail === 'object') return JSON.stringify(detail);
  return '';
}

/** Extract a renderable message from an axios-style error. */
export function errorMessageOf(err: any, fallback?: string): string {
  const data = err?.response?.data;
  const fromDetail = detailMessage(data?.detail);
  if (fromDetail) return fromDetail;
  return str(fallback) ?? str(data?.msg) ?? str(err?.message) ?? 'Request failed';
}
