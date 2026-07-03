import axios from 'axios';

const basePath = (import.meta.env.VITE_URLPATH || '').trim().replace(/^\/+|\/+$/g, '');
const apiBase = basePath ? `/${basePath}/api` : '/api';

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
      const message = error.response?.data?.detail || error.response?.data?.msg || error.message || 'Request failed';
      window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, {
        detail: { status, message, url: requestUrl },
      }));
    }

    return Promise.reject(error);
  }
);

export default apiClient;
