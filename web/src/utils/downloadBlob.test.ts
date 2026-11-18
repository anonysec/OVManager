// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, expect, it, vi } from 'vitest';
import { downloadBlob } from './downloadBlob';

afterEach(() => {
  vi.restoreAllMocks();
});

it('revokes the object URL only after the click is consumed', async () => {
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

  downloadBlob(new Blob(['x']), 'file.zip');

  expect(create).toHaveBeenCalledTimes(1);
  expect(click).toHaveBeenCalledTimes(1);
  expect(revoke).not.toHaveBeenCalled();

  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(revoke).toHaveBeenCalledWith('blob:test');
});
