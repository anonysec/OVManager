// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import axios from 'axios';

// API base comes from the <base href> the backend injects, so it always
// matches the prefix the panel is served under (e.g. "/dashboard/api").
const basePath = (document.querySelector('base')?.getAttribute('href') || '/').replace(/^\/+|\/+$/g, '');
// Exported for non-axios consumers (the SSE live stream uses it directly).
export const apiBase = basePath ? `/${basePath}/api` : '/api';

export const urlPath = basePath ? `/${basePath}` : '';

const apiClient = axios.create({ baseURL: apiBase });
let refreshPromise = null;
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
    const isRefreshRequest = requestUrl.includes('/refresh');

    if (status === 401 && !isLoginRequest && !isRefreshRequest) {
      const refreshToken = localStorage.getItem('refreshToken');
      if (refreshToken) {
        try {
          if (!refreshPromise) {
            refreshPromise = axios.post(
              `${apiBase}/refresh`,
              {},
              { headers: { Authorization: `Bearer ${refreshToken}` } }
            ).then((res) => {
              const newToken = res.data.access_token;
              localStorage.setItem('authToken', newToken);
              // Store the rotated refresh token returned by the server.
              // The backend revokes the old one on each use, so we must
              // persist the new one or the next refresh call will fail.
              if (res.data.refresh_token) {
                localStorage.setItem('refreshToken', res.data.refresh_token);
              }
              return newToken;
            }).finally(() => {
              refreshPromise = null;
            });
          }
          const newToken = await refreshPromise;
          // Retry original request with the one shared refreshed token.
          error.config.headers.Authorization = `Bearer ${newToken}`;
          return apiClient(error.config);
        } catch {
          // Refresh failed — force logout
        }
      }
      localStorage.removeItem('authToken');
      localStorage.removeItem('refreshToken');
      localStorage.removeItem('userRole');
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    } else if (status === 401 && isRefreshRequest) {
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
