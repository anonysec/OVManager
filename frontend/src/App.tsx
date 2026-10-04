import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';
import SectionBoundary from './components/ui/SectionBoundary';
import { SkeletonPanel, SkeletonBlock } from './components/ui/Skeleton';

import favicon from './assets/ovmanager-character-clean.png';

// Each factory is a named const so useRoutePrefetch can reuse it without
// creating a second, separate chunk.
const loadLogin = () => import('./pages/LoginPage');
const loadClaim = () => import('./pages/ClaimPage');
const loadDashboard = () => import('./pages/DashboardLayout');
const loadServerStats = () => import('./pages/ServerStats');
const loadUsers = () => import('./pages/UserManagement');
const loadNodes = () => import('./pages/NodeManagement');
const loadHealth = () => import('./pages/HealthCenter');
const loadSettings = () => import('./pages/Settings');
const loadAudit = () => import('./pages/AuditLog');
const loadAdmins = () => import('./pages/AdminManagement');
const loadSetup = () => import('./pages/SetupWizard');

const LoginPage = lazy(loadLogin);
const ClaimPage = lazy(loadClaim);
const DashboardLayout = lazy(loadDashboard);
const ServerStats = lazy(loadServerStats);
const UserManagement = lazy(loadUsers);
const NodeManagement = lazy(loadNodes);
const HealthCenter = lazy(loadHealth);
const Settings = lazy(loadSettings);
const AuditLog = lazy(loadAudit);
const AdminManagement = lazy(loadAdmins);
const SetupWizard = lazy(loadSetup);

const link = document.createElement('link');
link.rel = 'icon';
link.type = 'image/png';
link.href = favicon;
document.head.appendChild(link);

// A shaped skeleton reserves the same space as the real content, so route
// changes do not shift layout.
const PageLoader = () => {
  const { t } = useTranslation();
  return (
  <div className="page-loader" role="status" aria-live="polite" aria-label={t('loading', 'Loading')}>
    <SkeletonBlock width={230} height={26} radius={8} />
    <div className="page-loader-grid">
      <SkeletonPanel lines={4} />
      <SkeletonPanel lines={4} />
      <SkeletonPanel lines={4} />
    </div>
    <SkeletonPanel lines={8} height={280} />
  </div>
  );
};

// requestIdleCallback keeps chunk warming off the critical path, so it never
// competes with the current route's own data fetching.
function useRoutePrefetch(isAuthenticated: boolean, userRole: string | null) {
  useEffect(() => {
    if (!isAuthenticated) return;

    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 200));
    const cancel = window.cancelIdleCallback || clearTimeout;

    const handle = idle(async () => {
      // Ordered by likelihood of being visited from the dashboard.
      const queue: Array<() => Promise<unknown>> = [loadUsers, loadNodes, loadHealth, loadSettings];
      if (userRole === 'owner') queue.push(loadAdmins);
      // Chained sequentially so prefetching never saturates the connection pool.
      for (const load of queue) {
        try {
          await load();
        } catch {
          /* best-effort prefetch — the route loads on demand anyway */
        }
      }
    });

    return () => cancel(handle);
  }, [isAuthenticated, userRole]);
}

// Without this a deep scroll position carries over into the next page and it
// looks like content is missing.
function useScrollReset() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
  }, [pathname]);
}

// Named so a crash is scoped to one section: navigating to another page mounts
// clean instead of leaving a sticky error screen.
const Page = ({ name, children }: { name: string; children: React.ReactNode }) => (
  <SectionBoundary name={name}>
    <Suspense fallback={<PageLoader />}>{children}</Suspense>
  </SectionBoundary>
);

function App({ onReady }: { onReady?: () => void }) {
  const { isAuthenticated, userRole } = useAuth();

  useRoutePrefetch(isAuthenticated, userRole);
  useScrollReset();

  // Lets main.tsx drop the static boot shell once the app has committed.
  useEffect(() => { onReady?.(); }, [onReady]);

  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route
            path="/login"
            element={isAuthenticated ? <Navigate to="/" /> : <Page name="login"><LoginPage /></Page>}
          />
          <Route
            path="/claim"
            element={isAuthenticated ? <Navigate to="/" /> : <Page name="claim"><ClaimPage /></Page>}
          />
          {/* The installer's Ready card prints this URL, so it is the first
              thing an operator opens — and on a fresh install they hold a claim
              key and no session. Unauthenticated, it used to fall to the
              catch-all and become /login: no way to reach the claim page, for
              the one person holding a claim key.

              DashboardLayout is rendered here rather than nesting this under
              path="/", because nesting puts it behind that route's own
              isAuthenticated guard — the unauthenticated visitor would be sent
              to /login again, which is the bug. Declaring a second, sibling
              /setup does not work either: React Router scores a sibling static
              segment above a nested one, so it matches regardless of auth, and
              rendering the wizard from there strips the chrome (sidebar,
              breadcrumb, logout, theme, language) — an owner part-way through
              setup could reach no other page and could not log out. */}
          <Route
            path="/setup"
            element={
              isAuthenticated ? <DashboardLayout /> : <Navigate to="/claim" replace />
            }>
            <Route index element={<Page name="setup"><SetupWizard /></Page>} />
          </Route>
          <Route
            path="/"
            element={isAuthenticated ? <DashboardLayout /> : <Navigate to="/login" />}>
            <Route index element={<Page name="dashboard"><ServerStats /></Page>} />
            <Route path="users" element={<Page name="users"><UserManagement /></Page>} />
            {userRole === 'owner' && <Route path="nodes" element={<Page name="nodes"><NodeManagement /></Page>} />}
            <Route path="health" element={<Page name="health"><HealthCenter /></Page>} />
            {userRole === 'owner' && <Route path="audit" element={<Page name="audit"><AuditLog /></Page>} />}
            {userRole === 'owner' && <Route path="admins" element={<Page name="admins"><AdminManagement /></Page>} />}
            <Route path="settings" element={<Page name="settings"><Settings /></Page>} />
          </Route>
          <Route path="*" element={<Navigate to={isAuthenticated ? "/" : "/login"} />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}

export default App;
