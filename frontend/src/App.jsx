import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';
import SectionBoundary from './components/ui/SectionBoundary';
import { SkeletonPanel, SkeletonBlock } from './components/ui/Skeleton';

import favicon from './assets/ovmanager-character-clean.png';

// Lazy-loaded pages for code splitting. Each factory is hoisted to a named
// const so it can be reused for prefetching (see prefetchRoutes below) without
// creating a second, separate chunk.
const loadLogin = () => import('./pages/LoginPage');
const loadDashboard = () => import('./pages/DashboardLayout');
const loadServerStats = () => import('./pages/ServerStats');
const loadUsers = () => import('./pages/UserManagement');
const loadNodes = () => import('./pages/NodeManagement');
const loadSettings = () => import('./pages/Settings');
const loadAudit = () => import('./pages/AuditLog');
const loadMaintenance = () => import('./pages/Maintenance');
const loadAdmins = () => import('./pages/AdminManagement');

const LoginPage = lazy(loadLogin);
const DashboardLayout = lazy(loadDashboard);
const ServerStats = lazy(loadServerStats);
const UserManagement = lazy(loadUsers);
const NodeManagement = lazy(loadNodes);
const Settings = lazy(loadSettings);
const AuditLog = lazy(loadAudit);
const Maintenance = lazy(loadMaintenance);
const AdminManagement = lazy(loadAdmins);

// Set favicon
const link = document.createElement('link');
link.rel = 'icon';
link.type = 'image/png';
link.href = favicon;
document.head.appendChild(link);

/**
 * Page-level loading state.
 *
 * Replaces the old centred spinner. A spinner communicates "something is
 * happening"; a shaped skeleton communicates "this is what is about to
 * appear", which measurably lowers perceived wait and — because it reserves
 * the same space as the real content — removes the layout shift that made
 * navigation feel janky.
 */
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

/**
 * Warm the chunks the user is most likely to need next, once the current page
 * is idle. Navigation then resolves from cache instead of a cold network
 * round-trip, which is the difference between an instant tab switch and a
 * visible skeleton.
 *
 * requestIdleCallback keeps this strictly off the critical path — it never
 * competes with the current route's own data fetching.
 */
function useRoutePrefetch(isAuthenticated, userRole) {
  useEffect(() => {
    if (!isAuthenticated) return;

    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 200));
    const cancel = window.cancelIdleCallback || clearTimeout;

    const handle = idle(() => {
      // Ordered by likelihood of being visited from the dashboard.
      const queue = [loadUsers, loadNodes, loadSettings];
      if (userRole === 'owner') queue.push(loadAdmins);
      // Chain sequentially so we never saturate the connection pool.
      queue.reduce((p, load) => p.then(() => load().catch(() => {})), Promise.resolve());
    });

    return () => cancel(handle);
  }, [isAuthenticated, userRole]);
}

/** Scroll to top on route change — otherwise a deep scroll position carries
 *  over into the next page and it looks like content is missing. */
function useScrollReset() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
  }, [pathname]);
}

/**
 * Wraps a routed page in its own error boundary + Suspense.
 *
 * Keyed by path so that navigating away from a crashed page gives you a clean
 * mount rather than a sticky error screen.
 */
const Page = ({ name, children }) => (
  <SectionBoundary name={name}>
    <Suspense fallback={<PageLoader />}>{children}</Suspense>
  </SectionBoundary>
);

function App({ onReady }) {
  const { isAuthenticated, userRole } = useAuth();

  useRoutePrefetch(isAuthenticated, userRole);
  useScrollReset();

  // Tell main.jsx the app has committed so it can drop the static boot shell.
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
            path="/"
            element={isAuthenticated ? <DashboardLayout /> : <Navigate to="/login" />}>
            <Route index element={<Page name="dashboard"><ServerStats /></Page>} />
            <Route path="users" element={<Page name="users"><UserManagement /></Page>} />
            <Route path="nodes" element={<Page name="nodes"><NodeManagement /></Page>} />
            {userRole === 'owner' && <Route path="audit" element={<Page name="audit"><AuditLog /></Page>} />}
            {userRole === 'owner' && <Route path="maintenance" element={<Page name="maintenance"><Maintenance /></Page>} />}
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
