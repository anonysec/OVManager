import { describe, it, expect } from 'vitest';
import { asList } from './apiData';

describe('asList', () => {
  it('accepts a bare array', () => {
    expect(asList([1, 2])).toEqual([1, 2]);
  });

  it('unwraps { data: { users } } — the current GET /users/ shape', () => {
    expect(asList({ data: { users: [{ name: 'a' }], total: 1 } }, 'users')).toEqual([{ name: 'a' }]);
  });

  it('unwraps { data: […] } for endpoints that still return a list', () => {
    expect(asList({ data: [{ id: 1 }] })).toEqual([{ id: 1 }]);
  });

  it('unwraps the axios envelope settle() yields (res.users.data)', () => {
    const axiosResponse = { data: { success: true, data: { users: [{ name: 'a' }], total: 1 } } };
    expect(asList(axiosResponse, 'users')).toEqual([{ name: 'a' }]);
  });

  it('returns [] for missing or malformed payloads', () => {
    expect(asList(null)).toEqual([]);
    expect(asList({})).toEqual([]);
    expect(asList({ data: { total: 0 } })).toEqual([]);
  });
});
