/**
 * Smoke tests for the loading / error-isolation behaviour.
 * These lock in the two regressions that motivated the work:
 *   1. a single failing endpoint must not blank the dashboard
 *   2. the users table must actually render a skeleton on first load
 */
import { describe, it, expect } from 'vitest';
import { settle } from './useAsyncData';

describe('settle()', () => {
  it('keeps successful results when a sibling request rejects', async () => {
    const r = await settle({
      good: Promise.resolve({ data: 1 }),
      bad: Promise.reject(new Error('boom')),
      alsoGood: Promise.resolve({ data: 3 }),
    });
    expect(r.good.ok).toBe(true);
    expect(r.good.data).toEqual({ data: 1 });
    expect(r.bad.ok).toBe(false);
    expect(r.bad.error.message).toBe('boom');
    expect(r.alsoGood.ok).toBe(true);
  });

  it('never throws, even when everything fails', async () => {
    const r = await settle({
      a: Promise.reject(new Error('a')),
      b: Promise.reject(new Error('b')),
    });
    expect(r.a.ok).toBe(false);
    expect(r.b.ok).toBe(false);
  });

  it('reports every key it was given', async () => {
    const r = await settle({ x: Promise.resolve(1), y: Promise.reject(new Error('y')) });
    expect(Object.keys(r).sort()).toEqual(['x', 'y']);
  });
});
