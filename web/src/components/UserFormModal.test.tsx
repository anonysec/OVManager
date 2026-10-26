// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The "unlimited devices" card sets the devices field to 0. The field's
 * `min` must accept 0, otherwise the browser's native constraint validation
 * blocks the submit and the form silently does nothing.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import UserFormModal from './UserFormModal';

describe('UserFormModal devices field', () => {
  it('accepts 0 devices (the unlimited option)', () => {
    render(
      <UserFormModal isOpen onClose={() => {}} onSaved={() => {}} defaults={{ days: 30, maxLogins: 1 }} />
    );
    fireEvent.click(screen.getByRole('button', { name: '∞' }));
    // The modal renders through a portal, so query the document, not the
    // render container.
    const input = document.querySelector('.uf-devices input[type="number"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.value).toBe('0');
    expect(input.checkValidity()).toBe(true);
  });
});
