// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import apiClient from '../services/api';
import NodeDrawer from './NodeDrawer';

describe('NodeDrawer limit policy', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (apiClient.get as any).mockResolvedValue({ data: { success: true, data: {} } });
    (apiClient.put as any).mockResolvedValue({ data: { success: true, msg: 'Saved' } });
  });

  it('loads and saves the per-node limit policy', async () => {
    render(
      <NodeDrawer
        node={{ id: 1, name: 'n', settings: { LimitPolicy: 'strict' } }}
        initialTab="settings"
        onClose={() => {}}
      />,
    );

    const select = await screen.findByLabelText('At the device limit');
    expect((select as HTMLSelectElement).value).toBe('strict');

    fireEvent.change(select, { target: { value: 'takeover' } });
    fireEvent.click(screen.getByRole('button', { name: /save tuning/i }));

    await waitFor(() => expect(apiClient.put).toHaveBeenCalled());
    const payload = (apiClient.put as any).mock.calls[0][1];
    expect(payload.settings.LimitPolicy).toBe('takeover');
  });
});
