// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, expect, it } from 'vitest';
import { formatBytes } from './format';

describe('formatBytes', () => {
  it('formats whole units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
  });

  it('handles a fractional axis tick without an undefined unit', () => {
    // Half of a 1 B chart peak used to render as "512.0 undefined".
    expect(formatBytes(0.5)).toBe('0.5 B');
  });
});
