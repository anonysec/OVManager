import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import apiClient, { AUTH_EXPIRED_EVENT } from '../services/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {

  const [token, setToken] = useState(localStorage.getItem('authToken'));
  const [userRole, setUserRole] = useState(localStorage.getItem('userRole'));

  const login = async (username, password) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await apiClient.post('/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    const newToken = response.data.access_token;

    // Decode token to get user role
    const payload = JSON.parse(atob(newToken.split('.')[1]));
    const role = payload.type;

    localStorage.setItem('authToken', newToken);
    localStorage.setItem('userRole', role);
    setToken(newToken);
    setUserRole(role);
  };

  const logout = useCallback(() => {
    localStorage.removeItem('authToken');
    localStorage.removeItem('userRole');
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
    const handleStorage = (e) => {
      if (e.key === 'authToken') {
        setToken(e.newValue);
        if (!e.newValue) setUserRole(null);
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  // Proactively log out when the JWT has expired. This covers the "left the tab
  // idle, came back, UI shows but nothing works" case: instead of waiting for a
  // request to 401, we check the token's exp on load and when the tab regains
  // focus, and bounce to login immediately if it's stale.
  useEffect(() => {
    const isTokenExpired = (jwt) => {
      try {
        const payload = JSON.parse(atob(jwt.split('.')[1]));
        if (!payload?.exp) return false;
        // exp is in seconds; compare with a small clock-skew allowance.
        return payload.exp * 1000 <= Date.now();
      } catch {
        return true; // malformed token -> treat as expired
      }
    };

    const checkExpiry = () => {
      const stored = localStorage.getItem('authToken');
      if (stored && isTokenExpired(stored)) {
        logout();
      }
    };

    checkExpiry();
    const onVisible = () => {
      if (document.visibilityState === 'visible') checkExpiry();
    };
    window.addEventListener('focus', checkExpiry);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.removeEventListener('focus', checkExpiry);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [logout]);

  const isAuthenticated = !!token;

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout, userRole }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
