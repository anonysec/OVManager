// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '../../i18n';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

let refreshTick = 0;
vi.mock('../../context/LiveContext', () => ({
  useLive: () => ({ refreshTick, subscribe: () => () => {}, unsubscribe: () => {}, streamConnected: false }),
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ userRole: 'owner' }),
}));

import apiClient from '../../services/api';
import { ToastProvider } from '../../context/ToastContext';
import { ThemeProvider } from '../../context/ThemeContext';
import SystemSection from './SystemSection';

const ok = (data: any) => Promise.resolve({ data: { success: true, data } });

describe('SystemSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    refreshTick = 0;
    (apiClient.get as any).mockImplementation((url: string) => {
      if (url.includes('/server/info')) return ok({ uptime: 10 });
      if (url.includes('/metrics/history')) return ok({ traffic: [{ total_used: 5, active_connections: 1 }] });
      if (url.includes('/updater/status')) return ok({});
      return ok({});
    });
  });

  it('fetches metrics history only once even across live ticks', async () => {
    const tree = (
      <MemoryRouter>
        <ThemeProvider><ToastProvider><SystemSection /></ToastProvider></ThemeProvider>
      </MemoryRouter>
    );
    const { rerender } = render(tree);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/server/info'));

    refreshTick += 1;
    rerender(tree);
    await new Promise((r) => setTimeout(r, 50));

    const metricsCalls = (apiClient.get as any).mock.calls.filter((c: any) => c[0] === '/metrics/history?hours=24');
    expect(metricsCalls).toHaveLength(1);
  });
});