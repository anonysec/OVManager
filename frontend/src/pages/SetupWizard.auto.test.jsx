// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * SetupWizard auto-dismiss: all three steps done -> stores the dismissal,
 * toasts, and leaves for Home without further clicks.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

vi.mock('../context/LiveContext', () => ({
  useLive: () => ({ subscribe: () => () => {}, unsubscribe: () => {}, streamConnected: false, refreshTick: 0 }),
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ userRole: 'owner' }),
}));

import apiClient from '../services/api';
import { ToastProvider } from '../context/ToastContext';
import SetupWizard from './SetupWizard';

const ok = (data) => Promise.resolve({ data });

const stubStorage = (initial = {}) => {
  const store = { ...initial };
  vi.stubGlobal('localStorage', {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  });
  return store;
};

describe('SetupWizard auto-dismiss', () => {
  let store;
  beforeEach(() => {
    vi.clearAllMocks();
    store = stubStorage({ 'ovmanager-setup-config-done': '1' });
    apiClient.get.mockImplementation((url) => {
      if (url === '/health/setup') return ok({ has_active_node: true, has_node: true, has_user: true });
      return ok({});
    });
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('leaves for Home once every step is done', async () => {
    let lastPath = '/setup';
    const Probe = () => {
      lastPath = useLocation().pathname;
      return null;
    };
    render(
      <MemoryRouter initialEntries={['/setup']}>
        <ToastProvider><Probe /><SetupWizard /></ToastProvider>
      </MemoryRouter>,
    );
    // The congratulations card renders first…
    expect(await screen.findByText(/all set/i)).toBeTruthy();
    // …then the wizard dismisses itself and navigates home.
    await waitFor(() => expect(lastPath).toBe('/'), { timeout: 6000 });
    expect(store['ovmanager-setup-dismissed']).toBe('1');
  });

  it('stays put while steps remain', async () => {
    let lastPath = '/setup';
    const Probe = () => {
      lastPath = useLocation().pathname;
      return null;
    };
    apiClient.get.mockImplementation((url) => {
      if (url === '/health/setup') return ok({ has_active_node: true, has_node: true, has_user: false });
      return ok({});
    });
    render(
      <MemoryRouter initialEntries={['/setup']}>
        <ToastProvider><Probe /><SetupWizard /></ToastProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/install a node/i)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 3200));
    expect(lastPath).toBe('/setup');
    expect(store['ovmanager-setup-dismissed'] ?? null).toBeNull();
  });
});
