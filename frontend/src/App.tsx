import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';
import SectionBoundary from './components/ui/SectionBoundary';
import { SkeletonPanel, SkeletonBlock } from './components/ui/Skeleton';

import favicon from './assets/ovmanager-character-clean.png';

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

function useRoutePrefetch(isAuthenticated: boolean, userRole: string | null) {
  useEffect(() => {
    if (!isAuthenticated) return;

    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 200));
    const cancel = window.cancelIdleCallback || clearTimeout;

    const handle = idle(async () => {
      const queue: Array<() => Promise<unknown>> = [loadUsers, loadNodes, loadHealth, loadSettings];
      if (userRole === 'owner') queue.push(loadAdmins);
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

function useScrollReset() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
  }, [pathname]);
}

const Page = ({ name, children }: { name: string; children: React.ReactNode }) => (
  <SectionBoundary name={name}>
    <Suspense fallback={<PageLoader />}>{children}</Suspense>
  </SectionBoundary>
);

function App({ onReady }: { onReady?: () => void }) {
  const { isAuthenticated, userRole } = useAuth();

  useRoutePrefetch(isAuthenticated, userRole);
  useScrollReset();

  useEffect(() => { onReady?.(); }, [onReady]);

  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route
            path="/login"
            element={isAuthenticated ? <Navigate to="/" /> : <Page name="login"><LoginPage /></Page>}
          />
          {/* The installer's Ready card prints this URL, so it is the first
              thing an operator opens, and now the only one: /claim is gone,
              folded into the two states of this route. A visitor with no session
              gets the claim form — the one person holding a claim key is
              exactly who must not be sent somewhere else. An owner gets the
              wizard inside DashboardLayout, because that layout is what
              supplies the sidebar, breadcrumb, logout, theme cycle and language
              picker; an owner part-way through setup could otherwise reach no
              other page and could not log out.

              The layout is rendered here rather than nesting this under path="/",
              which would put the whole route behind that branch's isAuthenticated
              guard and send the stranger to /login — the original bug. A sibling
              top-level /setup was tried too and is wrong twice over: React
              Router scores it above a nested one so it matches regardless of
              auth, and rendering the wizard from outside the layout strips the
              chrome. */}
          <Route
            path="/setup"
            element={
              isAuthenticated
                ? <DashboardLayout />
                : <Page name="claim"><ClaimPage /></Page>
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
