// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText } from './clipboard';

describe('copyText', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns false for nullish input', async () => {
    expect(await copyText(null)).toBe(false);
    expect(await copyText(undefined)).toBe(false);
  });

  it('returns a boolean for string input', async () => {
    const result = await copyText('hello');
    expect(typeof result).toBe('boolean');
  });

  it('cleans up the temporary textarea even when execCommand throws', async () => {
    if (!('execCommand' in document)) (document as any).execCommand = () => true;
    const exec = vi.spyOn(document as any, 'execCommand').mockImplementation(() => {
      throw new Error('boom');
    });
    const before = document.querySelectorAll('textarea').length;
    const result = await copyText('hello');
    const after = document.querySelectorAll('textarea').length;
    expect(result).toBe(false);
    expect(after).toBe(before);
    exec.mockRestore();
  });
});
