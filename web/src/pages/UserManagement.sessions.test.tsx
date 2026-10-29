// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

const liveMock = vi.hoisted(() => {
  const listeners = new Map<string, Set<() => void>>();
  return {
    listeners,
    subscribe: (event: string, callback: () => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(callback);
      return () => listeners.get(event)?.delete(callback);
    },
    emit: (event: string) => listeners.get(event)?.forEach((callback) => callback()),
  };
});

vi.mock('../context/LiveContext', () => ({
  useLive: () => ({ subscribe: liveMock.subscribe, unsubscribe: () => {}, streamConnected: false, refreshTick: 0 }),
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ userRole: 'owner' }),
}));

import apiClient from '../services/api';
import { ToastProvider } from '../context/ToastContext';
import UserManagement from './UserManagement';

const ok = (data: any) => Promise.resolve({ data: { success: true, data } });

beforeEach(() => {
  vi.clearAllMocks();
  liveMock.listeners.clear();
  const store: Record<string, string> = {};
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value); },
    removeItem: (key: string) => { delete store[key]; },
  });
  (apiClient.get as any).mockImplementation((url: string) => {
    if (url === '/users/') {
      return ok({ users: [{
        id: 1, uuid: 'u-1', name: 'alice', tag: null, is_active: true,
        expiry_date: '2099-01-01', total: null, used: 0, max_logins: 2,
      }] });
    }
    if (url === '/users/id/1/sessions') {
      return ok({
        active_connections: 1,
        max_logins: 2,
        mode: 'strict',
        policy: ['ok'],
        global_registry: [],
        global_registry_error: 'The panel does not currently collect global registry data.',
        nodes: [{
          node: 'nodeA', reachable: true, live_count: 1, auth_errors: 3,
          live_sessions: [{ common_name: '42' }],
        }],
      });
    }
    return ok({});
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('UserManagement session actions', () => {
  it('reruns once when a user invalidation arrives during an older list request', async () => {
    let resolveInitial!: (value: any) => void;
    const initialList = new Promise((resolve) => { resolveInitial = resolve; });
    const alice = {
      id: 1, uuid: 'u-1', name: 'alice', tag: null, is_active: true,
      expiry_date: '2099-01-01', total: null, used: 0, max_logins: 2,
    };
    const bob = {
      id: 2, uuid: 'u-2', name: 'bob', tag: null, is_active: true,
      expiry_date: '2099-01-01', total: null, used: 0, max_logins: 2,
    };
    let usersRequests = 0;
    (apiClient.get as any).mockImplementation((url: string) => {
      if (url === '/users/') {
        usersRequests += 1;
        return usersRequests === 1 ? initialList : ok({ users: [alice, bob] });
      }
      return ok({});
    });

    render(
      <MemoryRouter initialEntries={['/users']}>
        <ToastProvider><UserManagement /></ToastProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(usersRequests).toBe(1));

    await act(async () => { liveMock.emit('users.changed'); });
    expect(usersRequests).toBe(1);

    await act(async () => {
      resolveInitial({ data: { success: true, data: { users: [alice] } } });
    });
    expect(await screen.findByText('bob')).toBeTruthy();
    expect(usersRequests).toBe(2);
  });

  it('disconnects sessions through the implemented kick endpoint', async () => {
    (apiClient.post as any).mockResolvedValue({
      data: { success: true, msg: 'User kicked', data: { kicked: 2, nodes_skipped: [] } },
    });
    render(
      <MemoryRouter initialEntries={['/users']}>
        <ToastProvider><UserManagement /></ToastProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: /more actions alice/i }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /^sessions$/i }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Active / Max: 1/2')).toBeTruthy();
    expect(within(dialog).getByText('Registry: Unavailable')).toBeTruthy();
    expect(within(dialog).getByText('The panel does not currently collect global registry data.')).toBeTruthy();
    expect(within(dialog).getByText('42')).toBeTruthy();
    expect(within(dialog).getByText('3')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: /^disconnect/i }));
    // A second immediate click is guarded by isDisconnecting
    fireEvent.click(within(dialog).getByRole('button', { name: /^disconnect/i }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith('/users/id/1/kick'));
    expect((apiClient.post as any).mock.calls.filter(([url]: [string]) => url === '/users/id/1/kick')).toHaveLength(1);
    expect(apiClient.post).not.toHaveBeenCalledWith('/users/id/1/disconnect');
    await waitFor(() => expect(screen.getByText('2 session(s) terminated.')).toBeTruthy());
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/users/id/1/sessions'));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith('/users/'));
  });
});
