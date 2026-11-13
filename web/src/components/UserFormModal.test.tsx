// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The form starts with no expiry, no traffic cap and unlimited devices. The
 * expiry field switches between a day count and a date without shifting the
 * date across timezones.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import apiClient from '../services/api';
import UserFormModal from './UserFormModal';

const localDate = (date = new Date()) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

const addDaysLocal = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return localDate(date);
};

const renderCreate = () => render(
  <UserFormModal isOpen onClose={() => {}} onSaved={() => {}} defaults={{ days: 0, maxLogins: 0 }} />
);

const submit = async () => {
  fireEvent.change(document.querySelector('#uf-username') as HTMLInputElement, { target: { value: 'alice' } });
  fireEvent.submit(document.querySelector('.uf-form') as HTMLFormElement);
  await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
  return (apiClient.post as any).mock.calls[0][1];
};

describe('UserFormModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (apiClient.post as any).mockResolvedValue({ data: { success: true, data: {} } });
  });

  it('accepts 0 devices (the unlimited option)', () => {
    renderCreate();
    fireEvent.click(screen.getByRole('button', { name: '∞' }));
    const input = document.querySelector('.uf-devices input[type="number"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.value).toBe('0');
    expect(input.checkValidity()).toBe(true);
  });

  it('creates a user with no expiry, no quota and unlimited devices by default', async () => {
    renderCreate();
    const payload = await submit();
    expect(payload.expiry_date).toBe('');
    expect(payload.total).toBeNull();
    expect(payload.max_logins).toBe(0);
  });

  it('converts a day count to a local date', async () => {
    renderCreate();
    fireEvent.change(document.querySelector('#uf-expiry-days') as HTMLInputElement, { target: { value: '30' } });
    const payload = await submit();
    expect(payload.expiry_date).toBe(addDaysLocal(30));
  });

  it('submits a picked date unchanged', async () => {
    renderCreate();
    fireEvent.click(screen.getByRole('button', { name: 'Date' }));
    fireEvent.change(document.querySelector('#uf-expiry-date') as HTMLInputElement, { target: { value: '2099-01-01' } });
    const payload = await submit();
    expect(payload.expiry_date).toBe('2099-01-01');
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
