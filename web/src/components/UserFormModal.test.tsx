// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The "unlimited devices" card sets the devices field to 0. The field's
 * `min` must accept 0, otherwise the browser's native constraint validation
 * blocks the submit and the form silently does nothing.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import apiClient from '../services/api';
import UserFormModal from './UserFormModal';

describe('UserFormModal', () => {
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

  it('updates an existing user through the numeric API alias when available', async () => {
    (apiClient.put as any).mockResolvedValue({ data: { success: true } });
    render(
      <UserFormModal
        isOpen
        user={{ id: 42, uuid: 'stable-uuid', name: 'alice', expiry_date: '2099-01-01', total: null, max_logins: 2 }}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );

    fireEvent.submit(document.querySelector('.uf-form') as HTMLFormElement);
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledWith('/users/id/42', expect.any(Object)));
  });
});
