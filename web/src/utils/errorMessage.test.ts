// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, it, expect } from 'vitest';
import { detailMessage, errorMessageOf } from './errorMessage';

const err422 = (detail: unknown) => ({ response: { status: 422, data: { detail } } });

describe('detailMessage', () => {
  it('joins FastAPI 422 array detail by msg', () => {
    expect(detailMessage([
      { loc: ['body', 'password'], msg: 'String should have at least 8 characters', type: 'string_too_short' },
      { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
    ])).toBe('String should have at least 8 characters, Field required');
  });

  it('falls back to JSON for array entries without msg', () => {
    expect(detailMessage([{ loc: ['body'] }])).toBe('{"loc":["body"]}');
  });

  it('keeps a string detail as-is', () => {
    expect(detailMessage('Invalid claim key')).toBe('Invalid claim key');
  });

  it('stringifies a non-array object detail', () => {
    expect(detailMessage({ code: 'bad', n: 1 })).toBe('{"code":"bad","n":1}');
  });

  it('returns empty string for missing detail', () => {
    expect(detailMessage(undefined)).toBe('');
    expect(detailMessage(null)).toBe('');
  });
});

describe('errorMessageOf', () => {
  it('uses the caller fallback when detail is missing', () => {
    expect(errorMessageOf({ response: { data: {} } }, 'default message')).toBe('default message');
  });

  it('prefers detail over msg and message', () => {
    const err = { message: 'boom', response: { data: { detail: 'nope', msg: 'm' } } };
    expect(errorMessageOf(err, 'fb')).toBe('nope');
  });

  it('falls back to data.msg then err.message then a generic string', () => {
    expect(errorMessageOf({ response: { data: { msg: 'from msg' } } }, 'fb')).toBe('fb');
    expect(errorMessageOf({ response: { data: { msg: 'from msg' } } })).toBe('from msg');
    expect(errorMessageOf({ response: { data: {} } })).toBe('Request failed');
    expect(errorMessageOf(new Error('from message'))).toBe('from message');
    expect(errorMessageOf({})).toBe('Request failed');
  });

  it('never returns a non-string for a 422 array detail', () => {
    const out = errorMessageOf(err422([
      { loc: ['body', 'password'], msg: 'String should have at least 8 characters', type: 'string_too_short' },
    ]), 'fallback');
    expect(typeof out).toBe('string');
    expect(out).toContain('String should have at least 8 characters');
  });
});
