// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * A full resynchronization (such as a reconnect or foreground refresh) must
 * not replace an open Settings editor or discard the operator's typed value.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

let refreshTick = 0;
vi.mock('../context/LiveContext', () => ({
  useLive: () => ({ refreshTick, subscribe: () => () => {}, unsubscribe: () => {}, streamConnected: false }),
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ userRole: 'owner' }),
}));

import apiClient from '../services/api';
import { ToastProvider } from '../context/ToastContext';
import { ThemeProvider } from '../context/ThemeContext';
import Settings from './Settings';

const ok = (data: any) => Promise.resolve({ data: { success: true, data } });

const settings = {
  urlpath: 'dashboard',
  subscription_url_prefix: '',
  timezone: 'UTC',
  bot_enabled: false,
  owner_telegram_id: null,
  telegram_summary_time: '09:00',
  default_days: 30,
  default_traffic_gb: 100,
  default_max_users: 1,
};

describe('Settings live refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    refreshTick = 0;
    (apiClient.get as any).mockImplementation((url: string) => {
      if (url.includes('/settings')) return ok(settings);
      if (url.includes('/activity')) return ok([]);
      return ok({});
    });
  });

  it('keeps an open editor and its typed value when a live event lands', async () => {
    const tree = (
      <MemoryRouter initialEntries={['/settings']}>
        <ThemeProvider><ToastProvider><Settings /></ToastProvider></ThemeProvider>
      </MemoryRouter>
    );
    const { container, rerender } = render(tree);

    // Wait for the first load to settle, then open the URL-path editor.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Change panel URL path' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Change panel URL path' }));
    const input = container.querySelector('#general-urlpath') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.change(input, { target: { value: '/ovmanager' } });
    expect(input.value).toBe('/ovmanager');

    // A full resynchronization tick may reload shared settings while editing.
    refreshTick += 1;
    (apiClient.get as any).mockImplementation((url: string) => {
      if (url.includes('/settings')) return ok(settings);
      if (url.includes('/activity')) return ok([]);
      return ok({});
    });
    rerender(tree);

    // The editor must still be open, with the operator's value intact — the
    // card must not have been replaced by a loading skeleton.
    await waitFor(() => expect(container.querySelector('#general-urlpath')).toBeTruthy());
    expect((container.querySelector('#general-urlpath') as HTMLInputElement).value).toBe('/ovmanager');
    expect(screen.queryByText('Loading…')).toBeNull();
  });
});
