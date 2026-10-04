// TEMPORARY adversarial-review test. Delete after review.
// Mirrors main.tsx's provider stack exactly (main.tsx:51-64).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import './i18n';

const authState: any = { isAuthenticated: false, userRole: null };

vi.mock('./context/AuthContext', () => ({
  useAuth: () => authState,
  AuthContext: { Provider: ({ children }: any) => children },
}));

vi.mock('./services/api', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: {} })) },
  apiBase: '/api', urlPath: '', api: {},
  AUTH_EXPIRED_EVENT: 'auth:expired', API_ERROR_EVENT: 'api:error',
}));

vi.mock('./context/LiveContext', () => ({
  LiveProvider: ({ children }: any) => children,
  useLive: () => ({ subscribe: () => () => {}, unsubscribe: () => {}, streamConnected: false, refreshTick: 0 }),
}));

vi.mock('./context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark', cycleTheme: () => {} }),
  ThemeContext: { Provider: ({ children }: any) => children },
}));

import App from './App';
import { ToastProvider } from './context/ToastContext';

const Probe = () => {
  const loc = useLocation();
  return <div data-testid="path">{loc.pathname}</div>;
};

const stubStorage = () => {
  const store: Record<string, string> = {};
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
  });
};

// Same shape as main.tsx: <MemoryRouter><ToastProvider><App/></ToastProvider></MemoryRouter>
const renderAt = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <Probe />
    <ToastProvider>
      <App />
    </ToastProvider>
  </MemoryRouter>,
);

describe('route resolution for /setup', () => {
  beforeEach(() => { stubStorage(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('(b) unauthenticated /setup redirects to /claim, NOT /login', async () => {
    authState.isAuthenticated = false;
    authState.userRole = null;
    renderAt('/setup');
    await waitFor(() => {
      expect(screen.getByTestId('path')).toHaveTextContent('/claim');
    });
    expect(screen.getByTestId('path').textContent).not.toBe('/login');
  });

  it('(a) authenticated /setup renders SetupWizard (not deleted)', async () => {
    authState.isAuthenticated = true;
    authState.userRole = 'owner';
    renderAt('/setup');
    await waitFor(() => {
      expect(screen.getAllByText(/Setup wizard/i).length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId('path').textContent).toBe('/setup');
  });

  it('(c) /setup is NOT duplicated in both route blocks', () => {
    const src = require('fs').readFileSync('src/App.tsx', 'utf8');
    const matches = src.match(/path="(\/)?setup"/g) || [];
    expect(matches).toHaveLength(1);
  });

  it('(d) /setup matches the explicit route, not the * catch-all (catch-all would send to "/")', async () => {
    authState.isAuthenticated = true;
    authState.userRole = 'owner';
    renderAt('/setup');
    await waitFor(() => {
      expect(screen.getAllByText(/Setup wizard/i).length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId('path').textContent).toBe('/setup');
  });

  it('(layout) does /setup still render inside DashboardLayout chrome (sidebar/breadcrumb)?', async () => {
    authState.isAuthenticated = true;
    authState.userRole = 'owner';
    const { container } = renderAt('/setup');
    await waitFor(() => {
      expect(screen.getAllByText(/Setup wizard/i).length).toBeGreaterThan(0);
    });
    const opsLayout = container.querySelector('.ops-layout');
    const sidebar = container.querySelector('nav[aria-label], .sidebar, aside');
    console.log('OPS_LAYOUT_PRESENT=', !!opsLayout);
    console.log('SIDEBAR_PRESENT=', !!sidebar);
    console.log('BREADCRUMB_PRESENT=', !!container.querySelector('.ops-breadcrumb'));
    console.log('HTML_CLASSES=', [...container.querySelectorAll('div')].slice(0,3).map(d=>d.className).join(' | '));
  });
});