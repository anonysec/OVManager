// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * A refused timezone write answers HTTP 200 with {success:false}. The panel
 * must not toast "Saved." and must not store the rejected zone.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '../../i18n';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import apiClient from '../../services/api';
import { ToastProvider } from '../../context/ToastContext';
import DisplaySection from './DisplaySection';

describe('DisplaySection timezone save', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('surfaces a refused timezone instead of reporting success', async () => {
    (apiClient.put as any).mockResolvedValue({
      data: { success: false, msg: 'Invalid timezone: Asia/Theran' },
    });

    const { container } = render(
      <ToastProvider>
        <DisplaySection shared={{ loading: false, data: { timezone: 'UTC' } }} />
      </ToastProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Change timezone' }));
    fireEvent.change(container.querySelector('#display-tz') as HTMLInputElement, { target: { value: 'Asia/Theran' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/ }));

    await waitFor(() => {
      expect(screen.getByText('Invalid timezone: Asia/Theran')).toBeTruthy();
    });
    expect(screen.queryByText('Saved.')).toBeNull();
  });
});
