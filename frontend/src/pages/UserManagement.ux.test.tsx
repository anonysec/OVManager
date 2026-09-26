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
import UserManagement from './UserManagement';

const ok = (data) => Promise.resolve({ data: { success: true, data } });

const taggedUsers = (n) =>
  Array.from({ length: n }, (_, i) => ({
    id: i + 1, uuid: `u-${i + 1}`, name: `user${i + 1}`,
    tag: `label-${i + 1}`, is_active: true, expiry_date: '2099-01-01',
    total: null, used: 0, owner: 'admin',
  }));

const stubStorage = () => {
  const store = {};
  vi.stubGlobal('localStorage', {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  });
};

const baseMock = (users) => {
  apiClient.get.mockImplementation((url) => {
    if (url === '/users/') return ok({ users });
    return ok({});
  });
};

const renderPage = (users) => {
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
    // Deterministic debounce: real timers for render/findBy, then fake
    // timers so the 275ms pause fires synchronously (parallel workers
    // starve real timers — the historical flake).
    vi.useFakeTimers();
    fireEvent.change(input, { target: { value: 'user' } });
    fireEvent.change(input, { target: { value: 'user1' } });
    // Rapid keystrokes must not rewrite the URL synchronously.
    expect(getSearch()).toBe('');
    // Advance past the 275ms debounce and flush React's effect cycle.
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

describe('UserManagement tag chips', () => {
  beforeEach(() => { vi.clearAllMocks(); stubStorage(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('collapses past eight labels behind a +N more chip', async () => {
    renderPage(taggedUsers(10));
    const group = await screen.findByRole('group', { name: /user filters/i });
    const chipLabels = () => within(group).getAllByRole('button').map((b) => b.textContent);
    // localeCompare sorts label-10 second, so the 8 visible are 1,10,2..7.
    await waitFor(() => expect(chipLabels().join(' ')).toContain('label-7'));
    expect(chipLabels().join(' ')).not.toContain('label-8');
    fireEvent.click(within(group).getByText('+2 more'));
    await waitFor(() => expect(chipLabels().join(' ')).toContain('label-8'));
    fireEvent.click(within(group).getByText(/show less/i));
    await waitFor(() => expect(chipLabels().join(' ')).not.toContain('label-8'));
  });

  it('truncates long labels with the full text in the title', async () => {
    renderPage([{ id: 1, uuid: 'u-1', name: 'user1', tag: 'a-quite-long-label-value', is_active: true, expiry_date: '2099-01-01', total: null, used: 0, owner: 'admin' }]);
    const chip = await screen.findByTitle('a-quite-long-label-value');
    expect(chip.className).toContain('um-chip-tag');
  });
});
