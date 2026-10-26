// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The live stream does its own fetch, so the api client's 401 handling never
 * sees it. Without an explicit reaction, a dead session leaves the operator
 * looking at a frozen dashboard while every action fails.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import { LiveProvider, useLive } from './LiveContext';
import { AUTH_EXPIRED_EVENT } from '../services/api';

const makeControlledStream = () => {
  const queued: any[] = [];
  let pending: ((result: any) => void) | null = null;
  let closed = false;
  const close = () => {
    closed = true;
    if (pending) {
      const resolve = pending;
      pending = null;
      resolve({ done: true });
    }
  };
  return {
    body: {
      getReader: () => ({
        read: () => {
          if (queued.length) return Promise.resolve(queued.shift());
          if (closed) return Promise.resolve({ done: true });
          return new Promise((resolve) => { pending = resolve; });
        },
        cancel: () => { close(); return Promise.resolve(); },
      }),
    },
    send: (chunk: string) => {
      const result = { done: false, value: new TextEncoder().encode(chunk) };
      if (pending) {
        const resolve = pending;
        pending = null;
        resolve(result);
      } else queued.push(result);
    },
    close,
    get waiting() { return pending !== null; },
  };
};

describe('LiveProvider event invalidation', () => {
  let expired = false;
  let onExpired: (() => void) | null = null;

  beforeEach(() => {
    expired = false;
    localStorage.setItem('userRole', 'owner');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      body: null,
      text: async () => '',
      headers: new Headers(),
    }));
    onExpired = () => { expired = true; };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
  });

  afterEach(() => {
    if (onExpired) window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
    onExpired = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('ends the session when the stream answers 401', async () => {
    render(<LiveProvider><div>live</div></LiveProvider>);
    await waitFor(() => expect(expired).toBe(true));
  });

  it('skips fallback invalidation while hidden and resynchronizes when visible', async () => {
    let visibility: DocumentVisibilityState = 'hidden';
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
    const fallbackCallbacks: Array<() => void> = [];
    const originalSetInterval = globalThis.setInterval;
    vi.spyOn(globalThis, 'setInterval').mockImplementation(((handler: TimerHandler, delay?: number, ...args: any[]) => {
      if (delay === 8000 && typeof handler === 'function') {
        fallbackCallbacks.push(handler as () => void);
        return fallbackCallbacks.length as any;
      }
      return originalSetInterval(handler, delay, ...args);
    }) as typeof setInterval);

    let ticks = 0;
    const Probe = () => {
      const { subscribe } = useLive();
      useEffect(() => subscribe('tick', () => { ticks += 1; }), [subscribe]);
      return null;
    };

    render(<LiveProvider><Probe /></LiveProvider>);
    await waitFor(() => expect(fallbackCallbacks).toHaveLength(1));

    act(() => fallbackCallbacks[0]());
    expect(ticks).toBe(0);

    visibility = 'visible';
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(document.visibilityState).toBe('visible');
    expect(ticks).toBe(1);
  });

  it('routes domain-event bursts narrowly and uses ready for reconnect resync', async () => {
    const stream = makeControlledStream();
    const counts = { tick: 0, users: 0, usersChanged: 0, nodes: 0, nodesChanged: 0 };
    const userOperations: any[] = [];
    vi.stubGlobal('fetch', vi.fn((_url: string, init: any) => {
      init.signal.addEventListener('abort', stream.close, { once: true });
      return Promise.resolve({ ok: true, status: 200, body: stream.body });
    }));

    const Probe = () => {
      const { subscribe, refreshTick } = useLive();
      useEffect(() => {
        const off = [
          subscribe('tick', () => { counts.tick += 1; }),
          subscribe('users', () => { counts.users += 1; }),
          subscribe('users.changed', (data: any) => { counts.usersChanged += 1; userOperations.push(data?.op); }),
          subscribe('nodes', () => { counts.nodes += 1; }),
          subscribe('nodes.changed', () => { counts.nodesChanged += 1; }),
        ];
        return () => off.forEach((unsubscribe) => unsubscribe());
      }, [subscribe]);
      return <output data-testid="refresh-tick">{refreshTick}</output>;
    };

    const view = render(<LiveProvider><Probe /></LiveProvider>);
    await waitFor(() => expect(stream.waiting).toBe(true));
    await act(async () => {
      stream.send('event: ready\ndata: {"ts":1,"cap":50}\n\n');
    });
    await waitFor(() => expect(counts.tick).toBe(1));
    expect(screen.getByTestId('refresh-tick').textContent).toBe('1');

    await waitFor(() => expect(stream.waiting).toBe(true));
    await act(async () => {
      stream.send('event: users\ndata: {"op":"connections"}\n\nevent: nodes\ndata: {"op":"status"}\n\n');
    });
    await waitFor(() => {
      expect(counts.users).toBe(1);
      expect(counts.usersChanged).toBe(1);
      expect(counts.nodes).toBe(1);
      expect(counts.nodesChanged).toBe(1);
    });
    expect(userOperations).toEqual(['connections']);
    expect(counts.tick).toBe(1);
    expect(screen.getByTestId('refresh-tick').textContent).toBe('1');
    view.unmount();
  });
});
