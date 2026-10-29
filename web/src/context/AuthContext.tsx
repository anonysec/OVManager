/* eslint-disable react-refresh/only-export-components */
import { createContext, useState, useContext, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import apiClient, { AUTH_EXPIRED_EVENT } from '../services/api';

type AuthContextValue = {
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  claim: (claimKey: string, password: string, username?: string) => Promise<void>;
  logout: () => void;
  userRole: string | null;
  /** /owner-claim said nobody owns this panel yet → first run wants /setup. */
  claimable: boolean;
  /** an active setup key exists, so owner credentials can be recovered. */
  recoverable: boolean;
  /** true until the one mount-time claim check settles; gates the redirects. */
  claimPending: boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

/** Session is the server's HttpOnly cookie plus the UI hint kept here. */
type Session = { role: string; name: string };

function readStoredSession(): Session | null {
  try {
    const role = localStorage.getItem('userRole');
    if (!role) return null;
    return { role, name: localStorage.getItem('username') || '' };
  } catch { return null; }
}

function storeSession(data: any, fallbackName = '') {
  const role = data.role || null;
  const resolvedName = data.username || fallbackName || '';
  if (!role) throw new Error('Login response did not include a role');

  // The session token is NOT kept. The server set an HttpOnly cookie, and a
  // copy in localStorage would be readable by any script on this origin —
  // which is exactly what the cookie exists to prevent. Only the role and
  // the display name are kept, and neither is a secret.
  try {
    localStorage.setItem('userRole', role);
    if (resolvedName) localStorage.setItem('username', resolvedName);
    else localStorage.removeItem('username');
  } catch { /* blocked storage: session still lives in memory */ }
  return { role, name: resolvedName };
}

export const AuthProvider = ({ children }: { children: ReactNode }) => {

  const [session, setSession] = useState<Session | null>(readStoredSession);
  // No session at mount → find out whether setup still owns this panel, once.
  const [claimable, setClaimable] = useState(false);
  const [recoverable, setRecoverable] = useState(false);
  const [claimPending, setClaimPending] = useState(() => { try { return !localStorage.getItem('userRole'); } catch { return true; } });

  const login = async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await apiClient.post('/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    setSession(storeSession(response.data, username));
  };

  const claim = async (claimKey: string, password: string, username?: string) => {
    const response = await apiClient.post('/owner-claim', {
      claim_key: claimKey,
      password,
      ...(username ? { username } : {}),
    });

    setSession(storeSession(response.data));
  };

  const logout = useCallback(() => {
    // The session is a cookie, so the SERVER has to clear it: without this
    // the next request would still authenticate while the SPA shows the
    // login form. /logout is unauthenticated, so it works even for a session
    // that has already expired.
    apiClient.post('/logout', null).catch(() => { /* local logout must still complete */ });
    try { localStorage.removeItem('userRole'); localStorage.removeItem('username'); } catch { /* blocked storage */ }
    setSession(null);
  }, []);

  useEffect(() => {
    const handleExpired = () => logout();
    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired);
  }, [logout]);

  // First-run probe: one GET at mount, only when there is no session to
  // check it against. Resolves claimPending either way so the router never
  // waits on a hung request — failure means "not claimable", i.e. today's
  // /login.
  useEffect(() => {
    const hasSession = (() => { try { return !!localStorage.getItem('userRole'); } catch { return false; } })();
    if (hasSession) return;
    let alive = true;
    apiClient.get('/owner-claim')
      .then((res) => { if (alive) { setClaimable(!!res.data?.claimable); setRecoverable(!!res.data?.recoverable); } })
      .catch(() => { /* no answer → plain /login, as before */ })
      .finally(() => { if (alive) setClaimPending(false); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      // Another tab signed in or out: the role is the shared hint.
      if (e.key === 'userRole') {
        const name = (() => { try { return localStorage.getItem('username') || ''; } catch { return ''; } })();
        setSession(e.newValue ? { role: e.newValue, name } : null);
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);


  const isAuthenticated = !!session;
  const userRole = session?.role ?? null;

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, claim, logout, userRole, claimable, recoverable, claimPending }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
