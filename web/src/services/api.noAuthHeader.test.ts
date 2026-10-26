// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The session lives in an HttpOnly cookie. The SPA must not send a bearer
 * token: a token readable by JavaScript is exactly what the cookie exists to
 * prevent, and the cookie is sent on every same-origin request anyway.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('apiClient sends no Authorization header', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => '{"success":true,"data":{}}',
      headers: new Headers(),
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.resetModules();
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('sends no Authorization header, even with a token in storage', async () => {
    localStorage.setItem('authToken', 'SECRET-TOKEN');
    const api = (await import('./api')).default;
    await api.get('/settings');

    expect(fetchMock).toHaveBeenCalled();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it('sends the cookie with the request', async () => {
    const api = (await import('./api')).default;
    await api.get('/settings');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe('same-origin');
  });
});
