// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { detailMessage } from '../utils/errorMessage';

export const apiBase = '/api';


export const AUTH_EXPIRED_EVENT = 'auth:expired';
export const API_ERROR_EVENT = 'api:error';

const DEFAULT_TIMEOUT = 30000;

export type ResponseType = 'blob' | 'arraybuffer';
export type QueryParams = Record<string, unknown>;
export type RequestHeaders = Record<string, string>;

export interface RequestConfig {
  params?: QueryParams | null;
  timeout?: number;
  responseType?: ResponseType;
  headers?: RequestHeaders;
  validateStatus?: (status: number) => boolean;
}

// `data` defaults to `any`: the body is arbitrary JSON and every caller reads
// it untyped (same escape hatch axios exposes via `AxiosResponse<T = any>`).
export interface ApiResponse<T = any> {
  data: T;
  status: number;
  headers: Record<string, string>;
  config: { url: string };
}

interface ApiError extends Error {
  config?: { url: string };
  response?: { status: number; data: unknown };
}

function withQuery(url: string, params?: QueryParams | null): string {
  if (!params) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) qs.append(k, String(v));
  }
  const q = qs.toString();
  return q ? `${url}${url.includes('?') ? '&' : '?'}${q}` : url;
}

function lowerHeaders(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  headers.forEach((v, k) => { out[k.toLowerCase()] = v; });
  return out;
}

async function parseBody(res: Response, responseType?: ResponseType): Promise<unknown> {
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

const normalizePath = (url: string) => {
  try {
    return new URL(url, window.location.origin).pathname;
  } catch {
    return url.split(/[?#]/)[0];
  }
};

const isPreAuth = (url: string) => {
  const path = normalizePath(url).replace(/\/+$/, '') || '/';
  return path === '/login' || path === '/owner-claim' || path === '/owner-claim/verify';
};

function handleAuthExpired(requestUrl: string) {
  if (isPreAuth(requestUrl)) return;
  // The session is a cookie: the server clears it on /logout. Only the UI
  // hint (the role) is cleared here; no secret is kept in storage.
  try { localStorage.removeItem('userRole'); localStorage.removeItem('username'); } catch { /* blocked storage */ }
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

// `data` is the parsed response body (external JSON), hence `any`.
function reportError(status: number, data: any, message: string, requestUrl: string) {
  if (isPreAuth(requestUrl)) return;
  const out = detailMessage(data?.detail) || data?.msg || message || 'Request failed';
  window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, {
    detail: { status, message: out, url: requestUrl },
  }));
}

// In-flight request deduplication cache.
// Key: `${method}:${url}:${JSON.stringify(params)}`
const inflightCache = new Map<string, Promise<ApiResponse<any>>>();

function makeCacheKey(method: string, url: string, params?: QueryParams | null): string {
  return `${method}:${url}:${JSON.stringify(params ?? {})}`;
}

async function request<T = any>(
  method: string,
  url: string,
  data?: unknown,
  config: RequestConfig = {},
): Promise<ApiResponse<T>> {
  const { params, timeout = DEFAULT_TIMEOUT, responseType, headers = {}, validateStatus } = config;
  const fullUrl = withQuery(`${apiBase}${url}`, params);

  // Deduplicate identical in-flight requests (GET only, no body).
  const cacheKey = makeCacheKey(method, url, params);
  if (method === 'GET' && data === undefined) {
    const cached = inflightCache.get(cacheKey) as Promise<ApiResponse<T>> | undefined;
    if (cached) return cached;
  }

  // Capture config values for the async closure.
  const capturedTimeout = timeout;
  const capturedValidateStatus: ((status: number) => boolean) | undefined = validateStatus;

  const promise = (async () => {
    // Capture validateStatus locally for TypeScript narrowing.
    const localValidateStatus = capturedValidateStatus;
    // No Authorization header: the session is the HttpOnly cookie the server
    // set at login, and it rides along on every same-origin request. A token
    // in JavaScript would be readable by any script on this origin, which is
    // exactly what the cookie prevents.
    const reqHeaders: Record<string, string> = { 'X-Requested-With': 'XMLHttpRequest', ...headers };

    let body: BodyInit | undefined;
    if (data !== undefined) {
      if (data instanceof FormData) {
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
    const timer = setTimeout(() => ctrl.abort(), capturedTimeout);
    let res: Response;
    try {
      res = await fetch(fullUrl, { method, headers: reqHeaders, body, credentials: 'same-origin', signal: ctrl.signal });
    } catch (e) {
      clearTimeout(timer);
      const err = new Error(
        (e as Error)?.name === 'AbortError'
          ? `Request timed out after ${capturedTimeout}ms`
          : ((e as Error)?.message || 'Network error'),
      ) as ApiError;
      err.config = { url };
      reportError(0, null, err.message, url);
      throw err;
    } finally {
      clearTimeout(timer);
    }

    const ok = typeof localValidateStatus === 'function' ? localValidateStatus(res.status) : (res.status >= 200 && res.status < 300);
    const parsed = await parseBody(res, responseType);
    const result: ApiResponse<T> = { data: parsed as T, status: res.status, headers: lowerHeaders(res.headers), config: { url } };
    if (ok) return result;

    if (res.status === 401) handleAuthExpired(url);
    const err = new Error(`Request failed with status ${res.status}`) as ApiError;
    err.response = { status: res.status, data: parsed };
    err.config = { url };
    reportError(res.status, parsed, err.message, url);
    throw err;
  })();

  if (method === 'GET' && data === undefined) {
    inflightCache.set(cacheKey, promise);
    void promise.then(
      () => { inflightCache.delete(cacheKey); },
      () => { inflightCache.delete(cacheKey); },
    );
  }
  return promise;
}

const apiClient = {
  get: <T = any>(url: string, config?: RequestConfig) => request<T>('GET', url, undefined, config),
  delete: <T = any>(url: string, config?: RequestConfig) => request<T>('DELETE', url, undefined, config),
  post: <T = any>(url: string, data?: unknown, config?: RequestConfig) => request<T>('POST', url, data, config),
  put: <T = any>(url: string, data?: unknown, config?: RequestConfig) => request<T>('PUT', url, data, config),
};

export default apiClient;