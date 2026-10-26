// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, it, expect } from 'vitest';
import { buildSubscriptionLink } from './subscriptionLink';

describe('buildSubscriptionLink', () => {
  it('falls back to the panel itself when no external prefix is set', () => {
    // A default install has no subscription_url_prefix, and the panel serves
    // the subscription page at /sub/<uuid> — the link must still be usable.
    expect(buildSubscriptionLink('https://panel.example', '', 'sub', 'u-1'))
      .toBe('https://panel.example/sub/u-1');
  });

  it('uses the configured subscription path', () => {
    expect(buildSubscriptionLink('https://panel.example', '', 'vpn', 'u-1'))
      .toBe('https://panel.example/vpn/u-1');
  });

  it('uses the external prefix when one is configured', () => {
    expect(buildSubscriptionLink('https://panel.example', 'https://sub.example', 'sub', 'u-1'))
      .toBe('https://sub.example/sub/u-1');
  });

  it('does not double a trailing slash', () => {
    expect(buildSubscriptionLink('https://panel.example/', 'https://sub.example/', 'sub', 'u-1'))
      .toBe('https://sub.example/sub/u-1');
  });

  it('returns nothing without a user', () => {
    expect(buildSubscriptionLink('https://panel.example', '', 'sub', '')).toBe('');
  });
});
