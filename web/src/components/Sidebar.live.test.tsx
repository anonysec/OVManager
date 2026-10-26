// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Sidebar from './Sidebar';

const liveMock = vi.hoisted(() => {
  const listeners = new Map<string, Set<(data?: any) => void>>();
  return {
    listeners,
    subscribe: (event: string, callback: (data?: any) => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(callback);
      return () => listeners.get(event)?.delete(callback);
    },
    unsubscribe: () => {},
    emit: (event: string, data?: any) => listeners.get(event)?.forEach((callback) => callback(data)),
  };
});
const apiMock = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../context/LiveContext', () => ({
  useLive: () => ({ subscribe: liveMock.subscribe, unsubscribe: liveMock.unsubscribe }),
}));
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ userRole: 'owner', logout: vi.fn() }),
}));
vi.mock('../services/api', () => ({ default: apiMock }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback || key }),
}));
vi.mock('./Logo', () => ({ default: () => null }));
vi.mock('./ConfirmModal', () => ({ default: () => null }));

beforeEach(() => {
  liveMock.listeners.clear();
  apiMock.get.mockReset().mockResolvedValue({
    data: { success: true, data: { users: [{ used: 10 }, { used: 20 }] } },
  });
});

afterEach(() => cleanup());

describe('Sidebar live stats invalidation', () => {
  it('does not refetch the user list for connection-only events', async () => {
    render(<MemoryRouter><Sidebar /></MemoryRouter>);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));

    await act(async () => { liveMock.emit('users.changed', { op: 'connections' }); });
    expect(apiMock.get).toHaveBeenCalledTimes(1);

    await act(async () => { liveMock.emit('users.changed', { op: 'reset-usage' }); });
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(2));
  });
});
