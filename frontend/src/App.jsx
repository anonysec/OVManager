import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import ErrorBoundary from './components/ErrorBoundary';

import favicon from './assets/ovmanager-character-clean.png';

// Lazy-loaded pages for code splitting
const LoginPage = lazy(() => import('./pages/LoginPage'));
const DashboardLayout = lazy(() => import('./pages/DashboardLayout'));
const ServerStats = lazy(() => import('./pages/ServerStats'));
const UserManagement = lazy(() => import('./pages/UserManagement'));
const NodeManagement = lazy(() => import('./pages/NodeManagement'));
const Settings = lazy(() => import('./pages/Settings'));
const AuditLog = lazy(() => import('./pages/AuditLog'));
const Maintenance = lazy(() => import('./pages/Maintenance'));
const AdminManagement = lazy(() => import('./pages/AdminManagement'));

// Set favicon
const link = document.createElement('link');
link.rel = 'icon';
link.type = 'image/png';
link.href = favicon;
document.head.appendChild(link);

const PageLoader = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '40vh' }}>
    <div style={{
      width: 32, height: 32,
      border: '3px solid var(--border-color)',
      borderTopColor: 'var(--accent-color)',
      borderRadius: '50%',
      animation: 'spin 0.8s linear infinite',
    }} />
  </div>
);

function App() {
  const { isAuthenticated, userRole } = useAuth();

  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route
            path="/login"
            element={isAuthenticated ? <Navigate to="/" /> : <LoginPage />}
          />
          <Route
            path="/"
            element={isAuthenticated ? <DashboardLayout /> : <Navigate to="/login" />}>
            <Route index element={<ServerStats />} />
            <Route path="users" element={<UserManagement />} />
            <Route path="nodes" element={<NodeManagement />} />
            {userRole === 'owner' && <Route path="audit" element={<AuditLog />} />}
            {userRole === 'owner' && <Route path="maintenance" element={<Maintenance />} />}
            {userRole === 'owner' && <Route path="admins" element={<AdminManagement />} />}
            <Route path="settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to={isAuthenticated ? "/" : "/login"} />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}

export default App;
