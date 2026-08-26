import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

import apiClient from '../services/api';
import ServerStats from './ServerStats';

const ok = (data) => Promise.resolve({ data: { success: true, data } });

describe('ServerStats resilience', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the dashboard when only /security/summary fails', async () => {
    apiClient.get.mockImplementation((url) => {
      if (url.includes('security')) return Promise.reject(new Error('500'));
      if (url.includes('server/info')) return ok({ cpu: 12, memory_percent: 40, disk_percent: 20 });
      if (url.includes('users')) return ok({ users: [] });
      if (url.includes('nodes')) return ok({ nodes: [] });
      if (url.includes('metrics')) return ok({ traffic: [] });
      return ok({});
    });

    render(<MemoryRouter><ServerStats /></MemoryRouter>);

    // The whole-page error state must NOT appear: four of five calls worked.
    await waitFor(() => {
      expect(screen.queryByText(/loadFailedTitle/i)).toBeNull();
    });
    // Server health (from the successful /server/info) still renders.
    await waitFor(() => expect(screen.getByText('12%')).toBeTruthy());
  });
});
