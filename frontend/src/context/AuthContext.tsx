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

function storeSession(data: any, fallbackName = '') {
  const newToken = data.access_token;
  const refreshToken = data.refresh_token;

  const role = data.role || null;
  const resolvedName = data.username || fallbackName || '';
  if (!role) throw new Error('Login response did not include a role');

  localStorage.setItem('authToken', newToken);
  if (refreshToken) {
    localStorage.setItem('refreshToken', refreshToken);
  } else {
    localStorage.removeItem('refreshToken');
  }
  localStorage.setItem('userRole', role);
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

  useEffect(() => {
    const handleExpired = () => logout();
    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired);
  }, [logout]);

  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'userRole') {
        setUserRole(e.newValue);
        return;
      }
      if (e.key === 'authToken') {
        setToken(e.newValue);
        if (!e.newValue) setUserRole(null);
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);


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
