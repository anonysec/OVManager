// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * A refused settings write answers HTTP 200 with {success:false}. The panel
 * URL path save must not report success, and must not navigate the operator
 * off the panel.
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
import GeneralSection from './GeneralSection';

const shared = { loading: false, data: { urlpath: 'dashboard', subscription_url_prefix: '' } };

describe('GeneralSection url path save', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('surfaces a refused save instead of reporting success', async () => {
    (apiClient.put as any).mockResolvedValue({
      data: { success: false, msg: "'api' is reserved and cannot be used as the panel URL path" },
    });

    const { container } = render(
      <ToastProvider>
        <GeneralSection shared={shared} />
      </ToastProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Change panel URL path' }));
    fireEvent.change(container.querySelector('#general-urlpath') as HTMLInputElement, { target: { value: 'api' } });
    fireEvent.click(screen.getByRole('checkbox'));
    // The section has several Save buttons; take the one in the URL-path editor.
    const urlEdit = container.querySelector('#general-urlpath')?.closest('.sp-inline-edit') as HTMLElement;
    const saveBtn = Array.from(urlEdit.querySelectorAll('button')).find((b) => /Save/.test(b.textContent || ''));
    fireEvent.click(saveBtn as Element);

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('reserved');
    });
    expect(screen.queryByText('Saved.')).toBeNull();
  });
});
