import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';
import SectionBoundary from './components/ui/SectionBoundary';
import { SkeletonPanel, SkeletonBlock } from './components/ui/Skeleton';

import favicon from './assets/ovmanager-character-clean.png';

const loadDashboard = () => import('./pages/DashboardLayout');
const loadServerStats = () => import('./pages/ServerStats');
const loadUsers = () => import('./pages/UserManagement');
const loadNodes = () => import('./pages/NodeManagement');
const loadSettings = () => import('./pages/Settings');
const loadLogs = () => import('./pages/Logs');
const loadSetup = () => import('./pages/SetupWizard');

const loadAuth = () => import('./pages/AuthPage');
const AuthPage = lazy(loadAuth);
const DashboardLayout = lazy(loadDashboard);
const ServerStats = lazy(loadServerStats);
const UserManagement = lazy(loadUsers);
const NodeManagement = lazy(loadNodes);
const Settings = lazy(loadSettings);
const Logs = lazy(loadLogs);
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
      <SkeletonPanel lines={4} label={t('loading', 'Loading…')} />
      <SkeletonPanel lines={4} label={t('loading', 'Loading…')} />
      <SkeletonPanel lines={4} label={t('loading', 'Loading…')} />
    </div>
    <SkeletonPanel lines={8} height={280} label={t('loading', 'Loading…')} />
  </div>
  );
};

function useRoutePrefetch(isAuthenticated: boolean, userRole: string | null) {
  useEffect(() => {
    if (!isAuthenticated) return;

    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 200));
    const cancel = window.cancelIdleCallback || clearTimeout;

    const handle = idle(async () => {
      const queue: Array<() => Promise<unknown>> = [loadUsers, loadNodes, loadSettings];
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
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [pathname]);
}

const Page = ({ name, children }: { name: string; children: React.ReactNode }) => (
  <SectionBoundary name={name}>
    <Suspense fallback={<PageLoader />}>{children}</Suspense>
  </SectionBoundary>
);

function App({ onReady }: { onReady?: () => void }) {
  const { isAuthenticated, userRole, claimable, claimPending } = useAuth();

  // Unauthenticated visitor: hold on the loader while the one-shot
  // /owner-claim check is in flight (no /login flash), then send a first-run
  // panel straight to /setup. null means "render the route as before".
  const firstRun = isAuthenticated
    ? null
    : claimPending
      ? <PageLoader />
      : claimable
        ? <Navigate to="/setup" replace />
        : null;

  useRoutePrefetch(isAuthenticated, userRole);
  useScrollReset();

  useEffect(() => { onReady?.(); }, [onReady]);

  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route
            path="/login"
            element={
              firstRun ?? (isAuthenticated ? <Navigate to="/" /> : <Page name="auth"><AuthPage /></Page>)
            }
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
                : <Page name="auth"><AuthPage /></Page>
            }>
            <Route index element={<Page name="setup"><SetupWizard /></Page>} />
          </Route>
          {/* The Health page is gone; old links and bookmarks land on Home. */}
          <Route path="/health" element={<Navigate to="/" />} />
          <Route
            path="/"
            element={
              firstRun ?? (isAuthenticated ? <DashboardLayout /> : <Navigate to="/login" />)
            }>
            <Route index element={<Page name="dashboard"><ServerStats /></Page>} />
            <Route path="users" element={<Page name="users"><UserManagement /></Page>} />
            {userRole === 'owner' && <Route path="nodes" element={<Page name="nodes"><NodeManagement /></Page>} />}
            <Route path="settings" element={<Page name="settings"><Settings /></Page>} />
            <Route path="logs" element={<Page name="logs"><Logs /></Page>} />
          </Route>
          <Route path="*" element={firstRun ?? <Navigate to={isAuthenticated ? "/" : "/login"} />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}

export default App;
