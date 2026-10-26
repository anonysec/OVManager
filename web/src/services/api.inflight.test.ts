// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('apiClient in-flight GET cleanup', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        status: 200,
        headers: new Headers(),
        text: async () => '{"success":true,"data":{}}',
      });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('allows a failed GET to be retried without creating a detached rejection', async () => {
    const api = (await import('./api')).default;

    await expect(api.get('/availability')).rejects.toThrow('offline');
    await new Promise((resolve) => setTimeout(resolve, 0));
    await expect(api.get('/availability')).resolves.toMatchObject({ status: 200 });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
