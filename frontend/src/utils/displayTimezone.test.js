import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { getDisplayTimezone, setDisplayTimezone } from './displayTimezone';
import { fmtDateTime, fmtDate } from './time';

const lsGet = (k) => {
  try {
    if (typeof localStorage !== 'undefined') return localStorage.getItem(k);
  } catch { /* blocked storage */ }
  return null;
};
const lsSet = (k, v) => {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(k, v);
  } catch { /* blocked storage */ }
};
const lsDel = (k) => {
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(k);
  } catch { /* blocked storage */ }
};

describe('displayTimezone', () => {
  let saved;
  beforeEach(() => {
    saved = lsGet('ovTimezone');
    lsDel('ovTimezone');
    setDisplayTimezone('UTC');
  });
  afterEach(() => {
    if (saved) lsSet('ovTimezone', saved);
    else lsDel('ovTimezone');
    setDisplayTimezone('UTC');
  });

  it('defaults to UTC with an empty cache', () => {
    expect(getDisplayTimezone()).toBe('UTC');
  });

  it('accepts a valid IANA zone and persists it', () => {
    expect(setDisplayTimezone('Asia/Tehran')).toBe('Asia/Tehran');
    expect(getDisplayTimezone()).toBe('Asia/Tehran');
    // Persisted when storage exists; in storage-less envs the in-memory
    // value above is what the UI reads.
    if (lsGet('ovTimezone') !== null || typeof localStorage !== 'undefined') {
      expect(lsGet('ovTimezone')).toBe('Asia/Tehran');
    }
  });

  it('rejects garbage without changing state', () => {
    expect(setDisplayTimezone('Bogus/Zone')).toBeNull();
    expect(getDisplayTimezone()).toBe('UTC');
  });
});

describe('time honours the display timezone', () => {
  afterEach(() => setDisplayTimezone('UTC'));

  it('fmtDateTime shifts hours with the zone (UTC 12:00 -> Tehran 15:30)', () => {
    const iso = '2026-09-13T12:00:00Z';
    const utc = fmtDateTime(iso, { timeZone: 'UTC' });
    setDisplayTimezone('Asia/Tehran');
    const teh = fmtDateTime(iso);
    expect(teh).not.toBe(utc);
    expect(teh).toContain('15:30');
  });

  it('explicit timeZone still wins over the stored default', () => {
    setDisplayTimezone('Asia/Tehran');
    expect(fmtDateTime('2026-09-13T12:00:00Z', { timeZone: 'UTC' })).toContain('12:00');
  });

  it('fmtDate renders a stable calendar date', () => {
    expect(fmtDate('2026-09-13')).toContain('2026');
  });
});
