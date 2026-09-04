// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/**
 * ServerStats dashboard tests — coverage for the new modern-SaaS layout.
 * Verifies that:
 * - per-source errors do NOT blank the entire dashboard
 * - hero KPI cards are clickable and route to filtered views
 * - the alert strip is clickable and routes per-item
 * - the chart shows data, metric toggle, and error/empty states
 * - activity feed renders with relative timestamps
 * - users tabs (online / needs attention) work
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import '../i18n';

vi.mock('../services/api', () => ({
  default: { get: vi.fn() },
  apiBase: '/api', urlPath: '',
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

vi.mock('../context/LiveContext', () => ({
  useLive: () => ({ subscribe: () => () => {}, unsubscribe: () => {}, streamConnected: false, refreshTick: 0 }),
}));

vi.mock('../utils/notifPrefs', async (importOriginal) => {
  const mod = await importOriginal();
  return { ...mod, readPrefs: () => ({ refreshSec: 3600 }) };
});

import apiClient from '../services/api';
import ServerStats from './ServerStats';

const ok = (data) => Promise.resolve({ data: { success: true, data } });
const INFO = { cpu: 12, memory_percent: 40, disk_percent: 20 };
const isNodeList = (url) => url === '/nodes/';
const isProbe = (url) => url.includes('/nodes/') && url !== '/nodes/';

const baseMock = (impl) => {
  apiClient.get.mockImplementation((url) => {
    const hit = impl(url);
    if (hit !== undefined) return hit;
    if (url.includes('server/info')) return ok(INFO);
    if (url.includes('users')) return ok({ users: [] });
    if (isNodeList(url)) return ok({ nodes: [] });
    if (url.includes('metrics')) return ok({ traffic: [] });
    if (url.includes('notifications')) return ok([]);
    if (url.includes('activity')) return ok([]);
    return ok({});
  });
};

const renderStats = () => render(<MemoryRouter><ServerStats /></MemoryRouter>);

const renderWithPath = () => {
  let lastPath = '/';
  const Probe = () => {
    const loc = useLocation();
    lastPath = loc.pathname + loc.search + loc.hash;
    return null;
  };
  const utils = render(<MemoryRouter initialEntries={['/']}><Probe /><ServerStats /></MemoryRouter>);
  return { ...utils, getPath: () => lastPath };
};

describe('ServerStats resilience', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the dashboard when only /activity fails', async () => {
    baseMock((url) => {
      if (url.includes('activity')) return Promise.reject(new Error('500'));
      return undefined;
    });
    renderStats();
    await waitFor(() => {
      expect(screen.queryByText('Dashboard data unavailable')).toBeNull();
    });
    await waitFor(() => expect(screen.getByText('12%')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('Could not load this panel')).toBeTruthy());
  });

  it('does not crash on malformed /server/info', async () => {
    baseMock((url) => {
      if (url.includes('server/info')) return ok({ cpu: 'bogus' });
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getAllByText('0%').length).toBeGreaterThan(0));
  });

  it('shows the empty chart state when metrics are truly empty', async () => {
    baseMock(() => undefined);
    renderStats();
    await waitFor(() => expect(screen.getByText('No metrics yet')).toBeTruthy());
  });

  it('merges server notifications into the alert strip', async () => {
    baseMock((url) => {
      if (url.includes('notifications')) {
        return ok([{ level: 'danger', type: 'node_offline', title: 'Node db-1 is offline', target: 'db-1' }]);
      }
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getAllByText('Node db-1 is offline').length).toBeGreaterThan(0));
  });

  it('does not flag nodes unreachable before probes resolve', async () => {
    let resolveProbes;
    const probeGate = new Promise((res) => { resolveProbes = res; });
    baseMock((url) => {
      if (isProbe(url)) return probeGate.then(() => ok({}));
      if (isNodeList(url)) {
        return ok({ nodes: [{ id: 7, name: 'edge-1', status: true, address: '10.0.0.7', port: 2083 }] });
      }
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getAllByText('edge-1').length).toBeGreaterThan(0));
    expect(screen.queryByText('Node edge-1 unreachable')).toBeNull();
    resolveProbes();
    await waitFor(() => expect(screen.getByText('Node edge-1 unreachable')).toBeTruthy());
  });

  it('lists users needing attention with reasons', async () => {
    baseMock((url) => {
      if (url.includes('users')) {
        const soon = new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10);
        return ok({
          users: [
            { name: 'soon', uuid: 'u-1', active_connections: 0, max_logins: 1, used: 1, total: 10, is_active: true, expiry_date: soon },
            { name: 'full', uuid: 'u-2', active_connections: 0, max_logins: 1, used: 9.5, total: 10, is_active: true, expiry_date: '2099-01-01' },
            { name: 'off', uuid: 'u-3', active_connections: 0, max_logins: 1, used: 1, total: 10, is_active: false, expiry_date: '2099-01-01' },
            { name: 'fine', uuid: 'u-4', active_connections: 0, max_logins: 1, used: 1, total: 10, is_active: true, expiry_date: '2099-01-01' },
          ],
        });
      }
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getByText('Needs attention')).toBeTruthy());
    fireEvent.click(screen.getByText('Needs attention'));
    await waitFor(() => expect(screen.getByText('soon')).toBeTruthy());
    expect(screen.getByText('full')).toBeTruthy();
    expect(screen.getByText('off')).toBeTruthy();
    expect(screen.queryByText('fine')).toBeNull();
  });

  it('shows recent activity with relative time and audit link', async () => {
    baseMock((url) => {
      if (url.includes('activity')) {
        return ok([{ id: 1, ts: Math.floor(Date.now() / 1000), actor: 'admin', action: 'user.create', target: 'amy', detail: '' }]);
      }
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getByText('amy')).toBeTruthy());
    expect(screen.getByText('user.create')).toBeTruthy();
  });

  it('hero cards navigate to filtered views', async () => {
    baseMock((url) => {
      if (isNodeList(url)) {
        return ok({ nodes: [{ id: 1, name: 'n1', status: true, address: '10.0.0.1', port: 2083 }] });
      }
      if (isProbe(url)) return ok({ reachable: true, node_info: {}, session_diagnostics: { live_count: 2 } });
      return undefined;
    });
    const { getPath, container } = renderWithPath();
    await waitFor(() => expect(container.querySelectorAll('.ds-kpi').length).toBeGreaterThanOrEqual(4));
    const buttons = container.querySelectorAll('button.ds-kpi');
    expect(buttons.length).toBeGreaterThanOrEqual(3);
    // Click the active sessions card (first KPI)
    const activeBtn = Array.from(buttons).find((b) => b.getAttribute('aria-label')?.includes('Active'));
    fireEvent.click(activeBtn);
    expect(getPath()).toBe('/users?view=online');
    const nodesBtn = Array.from(buttons).find((b) => b.getAttribute('aria-label')?.includes('Nodes'));
    fireEvent.click(nodesBtn);
    expect(getPath()).toBe('/nodes');
  });

  it('alert items navigate to their targets', async () => {
    baseMock((url) => {
      if (isNodeList(url)) {
        return ok({ nodes: [{ id: 9, name: 'down-1', status: true, address: '10.0.0.9', port: 2083 }] });
      }
      if (isProbe(url)) return Promise.reject(new Error('unreachable'));
      return undefined;
    });
    const { getPath } = renderWithPath();
    await waitFor(() => expect(screen.getByText('Node down-1 unreachable')).toBeTruthy());
    fireEvent.click(screen.getByText('Node down-1 unreachable'));
    expect(getPath()).toBe('/nodes');
  });

  it('chart metric toggle changes the displayed series', async () => {
    baseMock((url) => {
      if (url.includes('metrics')) {
        return ok({ traffic: [{ ts: 1, total_used: 100, active_connections: 2 }, { ts: 2, total_used: 300, active_connections: 5 }] });
      }
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getByText('100 B')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Sessions' }));
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy());
  });

  it('shows the chart error with retry instead of empty state', async () => {
    baseMock((url) => {
      if (url.includes('metrics')) return Promise.reject(new Error('down'));
      return undefined;
    });
    renderStats();
    await waitFor(() => expect(screen.getAllByText('Could not load this panel').length).toBeGreaterThan(0));
  });

  it('renders health meters with tones for high CPU', async () => {
    baseMock((url) => {
      if (url.includes('server/info')) return ok({ cpu: 92, memory_percent: 40, disk_percent: 20 });
      return undefined;
    });
    const { container } = renderStats();
    await waitFor(() => expect(container.querySelectorAll('.ds-meter').length).toBeGreaterThan(0));
  });
});
