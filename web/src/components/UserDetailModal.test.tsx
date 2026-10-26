// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * UserDetailModal must show the BILLED usage (`users.used`), not the sum of
 * the per-node lifetime baselines (`total_used`). The two are different
 * numbers: the first is what the panel bills and enforces, the second is
 * what the nodes have counted since they were first seen.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import apiClient from '../services/api';
import { formatBytes } from '../utils/format';
import UserDetailModal from './UserDetailModal';

const ok = (data: any) => Promise.resolve({ data: { success: true, data } });

const GIB = 1024 * 1024 * 1024;

const dataUsedCell = () => {
  // The modal renders through a portal, so query the document.
  const dt = Array.from(document.querySelectorAll('dt')).find((d) => d.textContent?.trim() === 'Data Used');
  return dt?.nextElementSibling?.textContent?.trim();
};

describe('UserDetailModal usage', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('shows the billed usage, not the node lifetime total', async () => {
    (apiClient.get as any).mockImplementation((url: string) => {
      if (url.includes('/traffic')) {
        // The nodes have counted 3 GiB since they were first polled; the panel
        // has only billed the user 0 B.
        return ok({ days: [], total_used: 3 * GIB, per_node: [{ name: 'n1', used: 3 * GIB }], used: 0 });
      }
      return ok({});
    });

    render(
      <UserDetailModal
        user={{ id: 42, uuid: 'u-1', name: 'amy', used: 0, total: GIB, is_active: true, max_logins: 1 }}
        isOpen
        onClose={() => {}}
      />
    );

    await waitFor(() => expect(document.querySelector('[role="progressbar"]')).toBeTruthy());
    expect(apiClient.get).toHaveBeenCalledWith('/users/id/42/traffic', { params: { days: 14 } });
    expect(dataUsedCell()).toBe(formatBytes(0));
    expect(document.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('0');
    expect(screen.queryByText(formatBytes(3 * GIB))).toBeNull();
  });
});
