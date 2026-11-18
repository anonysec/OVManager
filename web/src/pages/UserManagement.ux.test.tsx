// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * UserManagement UX: debounced search, capped tag chips, styled label input.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within, act } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
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
import UserManagement from './UserManagement';

const ok = (data: any) => Promise.resolve({ data: { success: true, data } });

const taggedUsers = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    id: i + 1, uuid: `u-${i + 1}`, name: `user${i + 1}`,
    tag: `label-${i + 1}`, is_active: true, expiry_date: '2099-01-01',
    total: null, used: 0, owner: 'admin',
  }));

const stubStorage = () => {
  const store: Record<string, string> = {};
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
  });
};

const baseMock = (users: any) => {
  (apiClient.get as any).mockImplementation((url: any) => {
    if (url === '/users/') return ok({ users });
    return ok({});
  });
};

const renderPage = (users: any) => {
  baseMock(users);
  let lastSearch = '';
  const Probe = () => {
    lastSearch = useLocation().search;
    return null;
  };
  const utils = render(
    <MemoryRouter initialEntries={['/users']}>
      <ToastProvider><Probe /><UserManagement /></ToastProvider>
    </MemoryRouter>,
  );
  return { ...utils, getSearch: () => lastSearch };
};

describe('UserManagement search debounce', () => {
  beforeEach(() => { vi.clearAllMocks(); stubStorage(); });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('waits for a pause before pushing the query to the URL', async () => {
    const { getSearch } = renderPage(taggedUsers(2));
    const input = await screen.findByLabelText(/search/i);
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: 'user' } });
    fireEvent.change(input, { target: { value: 'user1' } });
    expect(getSearch()).toBe('');
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(getSearch()).toContain('q=user1');
    vi.useRealTimers();
  });

  it('clears the query immediately from the clear button', async () => {
    const { getSearch } = renderPage(taggedUsers(2));
    const input = await screen.findByLabelText(/search/i);
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: 'user1' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(getSearch()).toContain('q=user1');
    vi.useRealTimers();
    fireEvent.click(screen.getByText(/^clear$/i));
    await waitFor(() => expect(getSearch()).toBe(''), { timeout: 8000 });
  });
});

// describe('UserManagement tag chips', () => { ... }) removed: label was deprecated and removed from user management.

describe('UserManagement bulk actions', () => {
  beforeEach(() => { vi.clearAllMocks(); stubStorage(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('counts a refused bulk change as a failure, not a success', async () => {
    // The panel answers HTTP 200 with {success:false} when it refuses to
    // activate an expired user. The bulk counter must not read that as done.
    (apiClient.put as any).mockResolvedValue({
      data: { success: false, msg: 'Cannot activate: user is expired' },
    });
    const expired = [
      { id: 1, uuid: 'u-1', name: 'exp1', is_active: false, expiry_date: '2000-01-01', total: null, used: 0, owner: 'admin' },
      { id: 2, uuid: 'u-2', name: 'exp2', is_active: false, expiry_date: '2000-01-01', total: null, used: 0, owner: 'admin' },
    ];
    renderPage(expired);

    fireEvent.click(await screen.findByRole('checkbox', { name: 'Select all' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Enable' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Enable' }));

    await waitFor(() => expect(screen.getByText('Enable: 0 done, 2 failed.')).toBeTruthy());
    expect(screen.queryByText('Enable: 2 done.')).toBeNull();
  });
});

describe('UserManagement row detail', () => {
  beforeEach(() => { vi.clearAllMocks(); stubStorage(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('opens the detail dialog from anywhere on the row', async () => {
    renderPage(taggedUsers(1));
    const row = await waitFor(() => {
      const el = document.querySelector('.dt-row');
      expect(el).toBeTruthy();
      return el as HTMLElement;
    });
    fireEvent.click(row);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('User: user1')).toBeTruthy();
  });

  it('does not open the detail dialog from the row checkbox', async () => {
    renderPage(taggedUsers(1));
    const checkbox = await screen.findByRole('checkbox', { name: 'Select row' });
    fireEvent.click(checkbox);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens the detail dialog with Enter on a focused row', async () => {
    renderPage(taggedUsers(1));
    const row = await waitFor(() => {
      const el = document.querySelector('.dt-row') as HTMLElement;
      expect(el).toBeTruthy();
      return el;
    });
    fireEvent.keyDown(row, { key: 'Enter' });
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('User: user1')).toBeTruthy();
  });
});

describe('UserManagement stats', () => {
  beforeEach(() => { vi.clearAllMocks(); stubStorage(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('excludes expired users from the active count', async () => {
    renderPage([
      { id: 1, uuid: 'u-1', name: 'alive', is_active: true, expiry_date: '2099-01-01', total: null, used: 0 },
      { id: 2, uuid: 'u-2', name: 'gone', is_active: true, expiry_date: '2000-01-01', total: null, used: 0 },
    ]);
    const label = await screen.findByText('Active Users');
    const card = label.closest('.ui-stat-card');
    expect(card?.querySelector('.ui-stat-card-value')?.textContent).toBe('1');
  });
});
