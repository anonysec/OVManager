import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import LoginPage from './pages/LoginPage';
import DashboardLayout from './pages/DashboardLayout';
import ServerStats from './pages/ServerStats';
import UserManagement from './pages/UserManagement';
import NodeManagement from './pages/NodeManagement';
import Settings from './pages/Settings';
import AuditLog from './pages/AuditLog';
import Maintenance from './pages/Maintenance';
import AdminManagement from './pages/AdminManagement';

import favicon from './assets/ovmanager-character-clean.png';

function App() {
  const { isAuthenticated, userRole } = useAuth();


  useEffect(() => {
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/png';
    link.href = favicon;
    document.head.appendChild(link);

    return () => {
      document.head.removeChild(link);
    };
  }, []);

  return (
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
        {userRole === 'main_admin' && <Route path="audit" element={<AuditLog />} />}
        {userRole === 'main_admin' && <Route path="maintenance" element={<Maintenance />} />}
        {userRole === 'main_admin' && <Route path="admins" element={<AdminManagement />} />}
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to={isAuthenticated ? "/" : "/login"} />} />
    </Routes>
  );
}

export default App;