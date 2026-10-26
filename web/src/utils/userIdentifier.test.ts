// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, expect, it } from 'vitest';
import { userApiPath, userIdentifierSegment } from './userIdentifier';

describe('user identifier routing', () => {
  it('prefers a safe numeric row ID for authenticated API requests', () => {
    expect(userApiPath({ id: 42, uuid: 'stable-uuid' })).toBe('/users/id/42');
    expect(userIdentifierSegment({ id: '42', uuid: 'stable-uuid' })).toBe('id/42');
  });

  it('falls back to the UUID for legacy or unsafe ID payloads', () => {
    expect(userApiPath({ uuid: 'stable-uuid' })).toBe('/users/stable-uuid');
    expect(userIdentifierSegment({ id: 0, uuid: 'stable-uuid' })).toBe('stable-uuid');
    expect(userIdentifierSegment({ id: Number.MAX_SAFE_INTEGER + 1, uuid: 'stable-uuid' })).toBe('stable-uuid');
    expect(userIdentifierSegment({ id: '9223372036854775808', uuid: 'stable-uuid' })).toBe('stable-uuid');
  });
});
