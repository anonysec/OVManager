import axios from 'axios';

const basePath = (import.meta.env.VITE_URLPATH || '').trim().replace(/^\/+|\/+$/g, '');
const apiBase = basePath ? `/${basePath}/api` : '/api';

export const urlPath = basePath ? `/${basePath}` : '';

const apiClient = axios.create({ baseURL: apiBase });
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
  (error) => {
    const status = error.response?.status;
    const requestUrl = error.config?.url || '';
    const isLoginRequest = requestUrl.includes('/login');

    if (status === 401 && !isLoginRequest) {
      localStorage.removeItem('authToken');
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
