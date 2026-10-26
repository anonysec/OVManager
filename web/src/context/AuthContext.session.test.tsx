// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The session lives in an HttpOnly cookie. The SPA must not keep a copy in
 * JavaScript: a token in localStorage is readable by ANY script on the panel's
 * origin, which is exactly what the HttpOnly cookie exists to prevent.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '../i18n';

const post = vi.fn();
vi.mock('../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { data: { claimable: false, recoverable: false } } }),
    post: (...args: any[]) => post(...args),
    put: vi.fn(),
    delete: vi.fn(),
  },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import { AuthProvider, useAuth } from './AuthContext';
import { ToastProvider } from './ToastContext';

const store: Record<string, string> = {};

const Login = () => {
  const { login } = useAuth();
  return <button onClick={() => login('admin', 'pw')}>go</button>;
};

describe('the session stays out of localStorage', () => {
  beforeEach(() => {
    for (const k of Object.keys(store)) delete store[k];
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => (k in store ? store[k] : null),
      setItem: (k: string, v: string) => { store[k] = String(v); },
      removeItem: (k: string) => { delete store[k]; },
    });
    post.mockReset();
    post.mockResolvedValue({ data: { access_token: 'SECRET-TOKEN', refresh_token: 'REFRESH', role: 'owner', username: 'admin' } });
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('writes no access or refresh token after a login', async () => {
    render(
      <ToastProvider>
        <AuthProvider><Login /></AuthProvider>
      </ToastProvider>
    );
    fireEvent.click(await screen.findByText('go'));

    await waitFor(() => expect(store.userRole).toBe('owner'));
    expect(store.authToken).toBeUndefined();
    expect(store.refreshToken).toBeUndefined();
    const dumped = JSON.stringify(store);
    expect(dumped).not.toContain('SECRET-TOKEN');
    expect(dumped).not.toContain('REFRESH');
  });
});
