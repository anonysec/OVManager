/* eslint-disable react-refresh/only-export-components */
import { createContext, useState, useContext, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import apiClient, { AUTH_EXPIRED_EVENT } from '../services/api';

type AuthContextValue = {
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  claim: (claimKey: string, password: string) => Promise<void>;
  logout: () => void;
  userRole: string | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Persist a session from a login-shaped response.
 *
 * Shared by login and the first-run claim, which returns the same body: one
 * place decides what a session means to this app.
 */
function storeSession(data: any, fallbackName = '') {
  const newToken = data.access_token;
  const refreshToken = data.refresh_token;

  // The backend issues an OPAQUE session token (random bytes), not a JWT,
  // so there is nothing in it to decode — identity comes from the response
  // body. Older builds decoded it, and because a non-JWT makes atob/JSON.parse
  // throw, LoginPage's catch reported every successful login as
  // "Incorrect username or password".
  const role = data.role || null;
  // Prefer the server's canonical spelling; fall back to what was typed.
  const resolvedName = data.username || fallbackName || '';
  if (!role) throw new Error('Login response did not include a role');

  localStorage.setItem('authToken', newToken);
  // Refresh tokens are a JWT-era artifact — the backend now issues opaque
  // sessions without one. Only persist if a server actually sends it.
  if (refreshToken) {
    localStorage.setItem('refreshToken', refreshToken);
  } else {
    localStorage.removeItem('refreshToken');
  }
  localStorage.setItem('userRole', role);
  // Persisted for the sidebar profile block, which previously read the JWT
  // "sub" claim — impossible with an opaque token.
  if (resolvedName) localStorage.setItem('username', resolvedName);
  return { token: newToken, role };
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {

  const [token, setToken] = useState(localStorage.getItem('authToken'));
  const [userRole, setUserRole] = useState(localStorage.getItem('userRole'));

  const login = async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await apiClient.post('/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    const { token: newToken, role } = storeSession(response.data, username);
    setToken(newToken);
    setUserRole(role);
  };

  // First run: the claim key the installer printed plus the password the
  // operator chooses. The owner row does not exist until this succeeds.
  const claim = async (claimKey: string, password: string) => {
    const response = await apiClient.post('/owner-claim', { claim_key: claimKey, password });

    const { token: newToken, role } = storeSession(response.data);
    setToken(newToken);
    setUserRole(role);
  };

  const logout = useCallback(() => {
    const accessToken = localStorage.getItem('authToken');
    const refreshToken = localStorage.getItem('refreshToken');
    if (accessToken || refreshToken) {
      apiClient.post('/logout', null, {
        headers: refreshToken ? { 'X-Refresh-Token': refreshToken } : undefined,
      }).catch(() => { /* local logout must still complete */ });
    }
    localStorage.removeItem('authToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('userRole');
    localStorage.removeItem('username');
    setToken(null);
    setUserRole(null);
  }, []);

  // When the API layer detects an expired/invalid token (401), it dispatches
  // AUTH_EXPIRED_EVENT. Resetting state here flips isAuthenticated to false,
  // and App's routes send the user to the login page (basename-aware).
  useEffect(() => {
    const handleExpired = () => logout();
    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired);
  }, [logout]);

  // Keep auth state in sync across browser tabs (e.g. logout in one tab).
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'authToken') {
        setToken(e.newValue);
        if (!e.newValue) setUserRole(null);
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  // Session expiry is authoritative on the server. The token is opaque, so the
  // client cannot inspect an exp claim — the previous implementation tried to,
  // and its catch treated any non-JWT as expired, which logged every user out
  // on load and immediately after login.
  //
  // Staleness is detected by the API layer instead: a 401 dispatches
  // AUTH_EXPIRED_EVENT, handled by the effect above.

  const isAuthenticated = !!token;

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, claim, logout, userRole }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
