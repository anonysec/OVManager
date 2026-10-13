// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/** First run: unauthenticated + /owner-claim claimable ⇒ straight to /setup,
 *  no /login frame ever mounted (recorded per mount, so a flash fails too). */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import './i18n';

// vi.mock factories run before the module body, so the log lives in vi.hoisted.
const { rendered } = vi.hoisted(() => ({ rendered: [] as string[] }));
const mark = (name: string) => { rendered.push(name); return null; };

vi.mock('./services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

vi.mock('./pages/LoginPage', () => ({ default: () => mark('login-page') }));
vi.mock('./pages/ClaimPage', () => ({ default: () => mark('claim-page') }));
vi.mock('./pages/DashboardLayout', () => ({ default: () => mark('dashboard-layout') }));

import apiClient from './services/api';
import { AuthProvider } from './context/AuthContext';
import App from './App';

const get = apiClient.get as unknown as ReturnType<typeof vi.fn>;

const renderApp = (path = '/') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );

const stubStorage = (initial: Record<string, string> = {}) => {
  const store: Record<string, string> = { ...initial };
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
  });
  return store;
};

beforeEach(() => {
  vi.clearAllMocks();
  stubStorage();
  rendered.length = 0;
  window.scrollTo = vi.fn();
});

afterEach(() => { vi.unstubAllGlobals(); });

describe('first-setup redirect', () => {
  it('claimable + no token: lands on /setup, login never mounts', async () => {
    get.mockResolvedValue({ data: { claimable: true } });
    renderApp('/');
    await waitFor(() => expect(rendered).toContain('claim-page'));
    expect(rendered).not.toContain('login-page');
  });

  it('claimable + no token visiting /login: lands on /setup, login never mounts', async () => {
    get.mockResolvedValue({ data: { claimable: true } });
    renderApp('/login');
    await waitFor(() => expect(rendered).toContain('claim-page'));
    expect(rendered).not.toContain('login-page');
  });

  it('not claimable + no token: /login as today', async () => {
    get.mockResolvedValue({ data: { claimable: false } });
    renderApp('/');
    await waitFor(() => expect(rendered).toContain('login-page'));
    expect(rendered).not.toContain('claim-page');
  });

  it('token present: dashboard even when claimable', async () => {
    localStorage.setItem('authToken', 't');
    localStorage.setItem('userRole', 'owner');
    get.mockResolvedValue({ data: { claimable: true } });
    renderApp('/');
    await waitFor(() => expect(rendered).toContain('dashboard-layout'));
    expect(rendered).not.toContain('claim-page');
    expect(rendered).not.toContain('login-page');
  });

  it('while the claim check is pending: neither login nor setup', async () => {
    let resolveClaim!: (v: unknown) => void;
    get.mockReturnValue(new Promise((res) => { resolveClaim = res; }));
    renderApp('/');
    await waitFor(() => expect(get).toHaveBeenCalledWith('/owner-claim'));
    expect(rendered).toEqual([]);
    resolveClaim({ data: { claimable: true } });
    await waitFor(() => expect(rendered).toContain('claim-page'));
    expect(rendered).not.toContain('login-page');
  });
});
