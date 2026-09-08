// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Minimal fetch-based API client replacing axios (same call-site contract):
//   apiClient.get(url, { params, timeout, responseType, headers, validateStatus })
//   apiClient.post/put(url, data, config) / apiClient.delete(url, config)
// Resolves { data, status, headers, config } — rejects with an error carrying
// .response { status, data }, .config { url } and .message, like axios did.

const basePath = (document.querySelector('base')?.getAttribute('href') || '/').replace(/^\/+|\/+$/g, '');
// Exported for non-fetch consumers (the SSE live stream uses it directly).
export const apiBase = basePath ? `/${basePath}/api` : '/api';

export const urlPath = basePath ? `/${basePath}` : '';

export const AUTH_EXPIRED_EVENT = 'auth:expired';
export const API_ERROR_EVENT = 'api:error';

const DEFAULT_TIMEOUT = 30000;

function withQuery(url, params) {
  if (!params) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) qs.append(k, String(v));
  }
  const q = qs.toString();
  return q ? `${url}${url.includes('?') ? '&' : '?'}${q}` : url;
}

function lowerHeaders(headers) {
  const out = {};
  headers.forEach((v, k) => { out[k.toLowerCase()] = v; });
  return out;
}

async function parseBody(res, responseType) {
  if (responseType === 'blob') return res.blob();
  if (responseType === 'arraybuffer') return res.arrayBuffer();
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function handleAuthExpired(requestUrl) {
  if (requestUrl.includes('/login')) return;
  localStorage.removeItem('authToken');
  localStorage.removeItem('refreshToken');
  localStorage.removeItem('userRole');
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

function reportError(status, data, message, requestUrl) {
  if (requestUrl.includes('/login')) return;
  const detail = data?.detail;
  let out;
  if (Array.isArray(detail)) {
    out = detail.map((d) => d.msg || JSON.stringify(d)).join(', ');
  } else if (typeof detail === 'object' && detail !== null) {
    out = JSON.stringify(detail);
  } else {
    out = detail || data?.msg || message || 'Request failed';
  }
  window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, {
    detail: { status, message: out, url: requestUrl },
  }));
}

async function request(method, url, data, config = {}) {
  const { params, timeout = DEFAULT_TIMEOUT, responseType, headers = {}, validateStatus } = config;
  const fullUrl = withQuery(`${apiBase}${url}`, params);

  const token = localStorage.getItem('authToken');
  const reqHeaders = { 'X-Requested-With': 'XMLHttpRequest', ...headers };
  if (token) reqHeaders.Authorization = `Bearer ${token}`;

  let body;
  if (data !== undefined) {
    if (data instanceof FormData) {
      // Let fetch set the multipart boundary itself.
      delete reqHeaders['Content-Type'];
      body = data;
    } else if (data instanceof URLSearchParams || typeof data === 'string') {
      body = data;
    } else {
      reqHeaders['Content-Type'] = reqHeaders['Content-Type'] || 'application/json';
      body = JSON.stringify(data);
    }
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(fullUrl, { method, headers: reqHeaders, body, credentials: 'same-origin', signal: ctrl.signal });
  } catch (e) {
    clearTimeout(timer);
    const err = new Error(e?.name === 'AbortError' ? `Request timed out after ${timeout}ms` : (e?.message || 'Network error'));
    err.config = { url };
    reportError(0, null, err.message, url);
    throw err;
  } finally {
    clearTimeout(timer);
  }

  const ok = validateStatus ? validateStatus(res.status) : (res.status >= 200 && res.status < 300);
  const parsed = await parseBody(res, responseType);
  const result = { data: parsed, status: res.status, headers: lowerHeaders(res.headers), config: { url } };
  if (ok) return result;

  if (res.status === 401) handleAuthExpired(url);
  const err = new Error(`Request failed with status ${res.status}`);
  err.response = { status: res.status, data: parsed };
  err.config = { url };
  reportError(res.status, parsed, err.message, url);
  throw err;
}

const apiClient = {
  get: (url, config) => request('GET', url, undefined, config),
  delete: (url, config) => request('DELETE', url, undefined, config),
  post: (url, data, config) => request('POST', url, data, config),
  put: (url, data, config) => request('PUT', url, data, config),
};

export default apiClient;
