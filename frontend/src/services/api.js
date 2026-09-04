// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import axios from 'axios';

// API base comes from the <base href> the backend injects, so it always
// matches the prefix the panel is served under (e.g. "/dashboard/api").
const basePath = (document.querySelector('base')?.getAttribute('href') || '/').replace(/^\/+|\/+$/g, '');
// Exported for non-axios consumers (the SSE live stream uses it directly).
export const apiBase = basePath ? `/${basePath}/api` : '/api';

export const urlPath = basePath ? `/${basePath}` : '';

const apiClient = axios.create({
  baseURL: apiBase,
  // Send the httpOnly ovm_session cookie alongside the Bearer header
  // (backend accepts both; cookie is XSS-proof, Bearer keeps bot/old compat).
  withCredentials: true,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
});
export const AUTH_EXPIRED_EVENT = 'auth:expired';
export const API_ERROR_EVENT = 'api:error';

apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('authToken');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  },
  (error) => Promise.reject(error)
);

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status;
    const requestUrl = error.config?.url || '';
    const isLoginRequest = requestUrl.includes('/login');

    // Backend sessions are opaque with sliding + absolute expiry. There is no
    // refresh flow (POST /refresh always 401 by design). Any 401 means the
    // session is gone — clear storage and drive forced re-login.
    if (status === 401 && !isLoginRequest) {
      localStorage.removeItem('authToken');
      localStorage.removeItem('refreshToken');
      localStorage.removeItem('userRole');
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    } else if (!isLoginRequest) {
      const detail = error.response?.data?.detail;
      let message;
      if (Array.isArray(detail)) {
        message = detail.map(d => d.msg || JSON.stringify(d)).join(', ');
      } else if (typeof detail === 'object' && detail !== null) {
        message = JSON.stringify(detail);
      } else {
        message = detail || error.response?.data?.msg || error.message || 'Request failed';
      }
      window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, {
        detail: { status, message, url: requestUrl },
      }));
    }

    return Promise.reject(error);
  }
);

export default apiClient;
