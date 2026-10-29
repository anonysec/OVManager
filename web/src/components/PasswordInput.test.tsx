// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PasswordInput from './PasswordInput';

describe('PasswordInput', () => {
  it('associates the label with the input', () => {
    const { container } = render(<PasswordInput label="Password" />);
    const label = container.querySelector('label');
    const input = container.querySelector('input');
    expect(label?.getAttribute('for')).toBe(input?.id);
  });
});
