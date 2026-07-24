import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import './styles.css'
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext.jsx';
import { ThemeProvider } from './context/ThemeContext.jsx';
import { ToastProvider } from './context/ToastContext.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import './i18n';

const raw = (import.meta.env.VITE_URLPATH || '').trim().replace(/^\/+|\/+$/g, '');
const base = raw ? raw : '';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename={base ? `/${base}` : ''}>
      <ThemeProvider>
        <AuthProvider>
          <ToastProvider>
            <ErrorBoundary>
              <App />
            </ErrorBoundary>
          </ToastProvider>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
