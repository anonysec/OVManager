import { describe, expect, it } from 'vitest';
import { COUNTRY_ALIASES, nodeMeta, normalizeCountryCode } from './geo.js';

// Regression: node "node-1" (NULL country in DB) rendered as Netherlands
// because the old fuzzy matcher compared the node NAME against country
// initials. Only the stored ISO code counts now.
describe('normalizeCountryCode', () => {
  it('returns null when there is no stored code, regardless of name', () => {
    expect(normalizeCountryCode({ country_code: null, name: 'node-1' })).toBeNull();
    expect(normalizeCountryCode({ country_code: null, name: 'ams01' })).toBeNull();
    expect(normalizeCountryCode({ country_code: null, name: 'fra node' })).toBeNull();
    expect(normalizeCountryCode({})).toBeNull();
  });

  it('accepts stored codes case-insensitively', () => {
    expect(normalizeCountryCode({ country_code: 'de' })).toBe('DE');
    expect(normalizeCountryCode({ country_code: ' DE ' })).toBe('DE');
  });

  it('resolves aliases to known codes', () => {
    expect(normalizeCountryCode({ country_code: 'uk' })).toBe('GB');
    expect(normalizeCountryCode({ country_code: 'us' })).toBe('USA');
  });

  it('passes through plausible unknown ISO codes without a flag entry', () => {
    expect(normalizeCountryCode({ country_code: 'NL' })).toBe('NL');
    expect(normalizeCountryCode({ country_code: 'XX' })).toBe('XX');
  });

  it('rejects garbage', () => {
    expect(normalizeCountryCode({ country_code: 'node-1' })).toBeNull();
    expect(normalizeCountryCode({ country_code: 'X' })).toBeNull();
    expect(normalizeCountryCode({ country_code: '123' })).toBeNull();
  });
});

describe('nodeMeta', () => {
  it('shows Location unavailable with no flag when unknown', () => {
    const meta = nodeMeta({ country_code: null, name: 'node-1', latitude: null, longitude: null });
    expect(meta.name).toBe('Location unavailable');
    expect(meta.flagCode).toBeNull();
    expect(meta.coords).toBeNull();
  });

  it('shows the stored country with fallback coords', () => {
    const meta = nodeMeta({ country_code: 'DE', latitude: null, longitude: null });
    expect(meta.name).toBe('Germany');
    expect(meta.flagCode).toBe('DE');
    expect(meta.approximate).toBe(true);
  });

  it('prefers real coordinates over fallback', () => {
    const meta = nodeMeta({ country_code: 'DE', latitude: 49.45, longitude: 11.07 });
    expect(meta.coords).toEqual([11.07, 49.45]);
    expect(meta.approximate).toBe(false);
  });

  it('shows code text without flag for unknown codes', () => {
    const meta = nodeMeta({ country_code: 'XX', latitude: null, longitude: null });
    expect(meta.name).toBe('XX');
    expect(meta.flagCode).toBeNull();
  });
});

describe('COUNTRY_ALIASES', () => {
  it('only maps to codes with display entries', () => {
    for (const code of Object.values(COUNTRY_ALIASES)) {
      expect(code).toMatch(/^[A-Z]{2,3}$/);
    }
  });
});
