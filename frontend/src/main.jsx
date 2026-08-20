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
import { getUrlPath } from './utils/panelUrl';
import { applyAccent, applyUiStyle } from './utils/uiPrefs';
import './i18n';

// Apply persisted UI preferences (custom accent, minimal style) before first paint.
try { applyAccent(); } catch { /* noop */ }
try { applyUiStyle(); } catch { /* noop */ }

// Router basename comes from the <base href> the backend injects, e.g.
// "/dashboard" when served at /dashboard/, "" when served at root. The
// frontend never hard-codes or builds the prefix itself.
const raw = getUrlPath();
const base = raw ? `/${raw}` : '';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename={base}>
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
