// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, expect, it } from 'vitest';
import { groupSecurityEvents } from './groupSecurityEvents';

describe('groupSecurityEvents', () => {
  it('collapses repeated user policy events and keeps the latest timestamp', () => {
    const events = [
      { action: 'max_logins', user: 'alice', node: 'a', ts: 10, severity: 'policy' },
      { action: 'max_logins', user: 'alice', node: 'a', ts: 20, severity: 'policy' },
      { action: 'max_logins', user: 'alice', node: 'a', ts: 15, severity: 'policy' },
      { action: 'max_logins', user: 'bob', node: 'a', ts: 5, severity: 'policy' },
    ];
    const grouped = groupSecurityEvents(events);
    expect(grouped).toHaveLength(2);
    const alice = grouped.find((event) => event.user === 'alice');
    expect(alice?.count).toBe(3);
    expect(alice?.ts).toBe(20);
    expect(grouped[0].user).toBe('alice');
  });

  it('keeps takeover failures separate from auth events', () => {
    const grouped = groupSecurityEvents([
      { action: 'takeover_failed', user: 'alice', node: 'a', ts: 1, severity: 'failure' },
      { action: 'takeover_failed', user: 'alice', node: 'a', ts: 2, severity: 'failure' },
    ]);
    expect(grouped).toHaveLength(1);
    expect(grouped[0].count).toBe(2);
  });
});
