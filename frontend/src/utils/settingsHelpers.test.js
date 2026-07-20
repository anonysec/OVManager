import { describe, it, expect } from 'vitest';
import { validateSubscription, buildSubUrl, SUB_PATH_RE } from './settingsHelpers';

// Minimal i18n stub: returns the key so we can assert which error fires.
const t = (key) => key;

describe('validateSubscription', () => {
  it('accepts empty prefix and path', () => {
    expect(validateSubscription('', '', t)).toBe('');
  });

  it('accepts a valid https prefix', () => {
    expect(validateSubscription('https://vpn.example.com/sub/', '', t)).toBe('');
  });

  it('accepts a valid http prefix', () => {
    expect(validateSubscription('http://10.0.0.1:8080/', '', t)).toBe('');
  });

  it('rejects a non-URL prefix', () => {
    expect(validateSubscription('not a url', '', t)).toBe('urlInvalid');
  });

  it('rejects a non-http(s) scheme', () => {
    expect(validateSubscription('ftp://example.com/', '', t)).toBe('urlSchemeHttp');
  });

  it('rejects a path with invalid characters', () => {
    expect(validateSubscription('', 'sub/path with spaces', t)).toBe('pathInvalid');
  });

  it('accepts a clean multi-segment path', () => {
    expect(validateSubscription('', 'sub/client', t)).toBe('');
  });
});

describe('buildSubUrl', () => {
  it('joins prefix, path and placeholder', () => {
    expect(buildSubUrl('https://vpn.example.com/', 'sub')).toBe('https://vpn.example.com/sub/{user_uuid}');
  });

  it('tolerates slashes in path', () => {
    expect(buildSubUrl('https://vpn.example.com/', '/sub/')).toBe('https://vpn.example.com/sub/{user_uuid}');
  });

  it('handles missing path', () => {
    expect(buildSubUrl('https://vpn.example.com/sub/', '')).toBe('https://vpn.example.com/sub/{user_uuid}');
  });
});

describe('SUB_PATH_RE', () => {
  it('matches valid segments, rejects spaces and special chars', () => {
    expect(SUB_PATH_RE.test('a/b-c_d')).toBe(true);
    expect(SUB_PATH_RE.test('bad path')).toBe(false);
    expect(SUB_PATH_RE.test('bad!')).toBe(false);
  });
});
