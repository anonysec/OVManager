import axios from 'axios';


// Respect VITE_URLPATH for baseURL when panel is installed under a subpath
const basePath = (import.meta.env.VITE_URLPATH || '').trim().replace(/^\/+|\/+$/g, '');
const apiBase = basePath ? `/${basePath}/api` : '/api';

const apiClient = axios.create({
  baseURL: apiBase
});

// Custom event fired when the backend rejects our token (expired/invalid).
// AuthContext listens for it and performs a clean logout + redirect, which
// keeps React Router's basename handling intact (a raw window.location redirect
// would drop the configured panel path prefix).
export const AUTH_EXPIRED_EVENT = 'auth:expired';


apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('authToken');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor: when the token is expired/invalid the backend returns
// 401. Without this, the UI keeps the stale token in localStorage, still renders
// the dashboard, but every request silently fails until a manual re-login.
// Here we clear the session and notify the app to go back to the login page.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const requestUrl = error.config?.url || '';

    // A failed login attempt is a normal 401, not a session expiry.
    const isLoginRequest = requestUrl.includes('/login');

    if (status === 401 && !isLoginRequest) {
      localStorage.removeItem('authToken');
      localStorage.removeItem('userRole');
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }

    return Promise.reject(error);
  }
);

export default apiClient;
