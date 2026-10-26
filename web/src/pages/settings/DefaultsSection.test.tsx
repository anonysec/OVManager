// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The default-devices hint says "0 = unlimited" and the input allows 0, so
 * the saved value must be 0 — not silently clamped to 1.
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
import DefaultsSection from './DefaultsSection';

describe('DefaultsSection devices', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('saves 0 devices (unlimited) instead of clamping it to 1', async () => {
    (apiClient.put as any).mockResolvedValue({ data: { success: true, data: {} } });

    const { container } = render(
      <ToastProvider>
        <DefaultsSection shared={{ loading: false, data: { default_days: 30, default_traffic_gb: 100, default_max_users: 0 } }} />
      </ToastProvider>
    );

    fireEvent.change(container.querySelector('#defaults-devices') as HTMLInputElement, { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/ }));

    await waitFor(() => expect((apiClient.put as any).mock.calls.length).toBe(1));
    expect((apiClient.put as any).mock.calls[0][1].default_max_users).toBe(0);
  });
});
