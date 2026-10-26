// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, expect, it, vi } from 'vitest';
import { createQueuedRefresh } from './queuedRefresh';

describe('createQueuedRefresh', () => {
  it('queues one trailing pass when invalidations arrive during an in-flight request', async () => {
    let finishFirst!: () => void;
    const firstRequest = new Promise<void>((resolve) => { finishFirst = resolve; });
    const work = vi.fn()
      .mockImplementationOnce(() => firstRequest)
      .mockResolvedValue(undefined);
    const refresh = createQueuedRefresh(work);

    const initial = refresh('mount');
    await Promise.resolve();
    const eventOne = refresh('users');
    const eventTwo = refresh('nodes');

    expect(work).toHaveBeenCalledTimes(1);
    expect(work).toHaveBeenCalledWith('mount');

    finishFirst();
    await Promise.all([initial, eventOne, eventTwo]);

    expect(work).toHaveBeenCalledTimes(2);
    expect(work).toHaveBeenNthCalledWith(2, 'nodes');
  });
});
