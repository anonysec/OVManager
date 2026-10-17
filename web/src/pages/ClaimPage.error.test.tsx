// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * ClaimPage error extraction: a FastAPI 422 `detail` ARRAY must reach the DOM
 * as a readable string — rendering it verbatim throws "Objects are not valid
 * as a React child" and trips the SectionBoundary.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    claim: vi.fn(), login: vi.fn(), logout: vi.fn(),
    isAuthenticated: false, claimable: true, claimPending: false, userRole: null,
  }),
}));

import apiClient from '../services/api';
import ClaimPage from './ClaimPage';

const httpError = (detail: unknown) => ({ response: { status: 422, data: { detail } } });

const submitVerify = (container: HTMLElement) => {
  const input = container.querySelector('#claim-key') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'setup-key' } });
  fireEvent.click(screen.getByRole('button', { name: /verify/i }));
};

describe('ClaimPage claimErrorOf', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('renders a 422 array detail as a readable message, no boundary', async () => {
    (apiClient.post as any).mockRejectedValue(httpError([
      { loc: ['body', 'password'], msg: 'String should have at least 8 characters', type: 'string_too_short' },
      { loc: ['body', 'username'], msg: 'Field required', type: 'missing' },
    ]));
    const { container } = render(
      <MemoryRouter initialEntries={['/setup']}><ClaimPage /></MemoryRouter>,
    );
    submitVerify(container);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('String should have at least 8 characters');
    expect(alert.textContent).toContain('Field required');
    expect(alert.textContent).not.toContain('[{');
  });

  it('keeps a string detail as-is', async () => {
    (apiClient.post as any).mockRejectedValue(httpError('Invalid setup key'));
    const { container } = render(
      <MemoryRouter initialEntries={['/setup']}><ClaimPage /></MemoryRouter>,
    );
    submitVerify(container);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Invalid setup key');
  });

  it('falls back to the default claim message when detail is missing', async () => {
    (apiClient.post as any).mockRejectedValue({ response: { status: 500, data: {} } });
    const { container } = render(
      <MemoryRouter initialEntries={['/setup']}><ClaimPage /></MemoryRouter>,
    );
    submitVerify(container);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('The claim failed. Check the key and try again.');
  });
});
