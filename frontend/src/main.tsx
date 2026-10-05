import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './tokens.css'
import './index.css'
import './styles.css'
import './pages/Dashboard.css'
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { ToastProvider } from './context/ToastContext';
import ErrorBoundary from './components/ErrorBoundary';
import { applyAccent } from './utils/uiPrefs';
import './i18n';

try { applyAccent(); } catch { /* noop */ }

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => { /* optional */ });
}

const raw = (() => {
  const el = typeof document !== 'undefined' ? document.querySelector('base') : null;
  const href = el?.getAttribute('href');
  if (!href) return '';
  let path: string;
  try {
    path = new URL(href, window.location.origin).pathname;
  } catch {
    path = href.startsWith('/') ? href : `/${href}`;
  }
  return path.replace(/^\/+|\/+$/g, '');
})();
const base = raw ? `/${raw}` : '';

function dismissBootSkeleton() {
  const shell = document.getElementById('app-skeleton');
  if (!shell) return;

  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion) {
    shell.remove();
    return;
  }

  shell.style.transition = 'opacity .18s ease';
  shell.style.opacity = '0';
  shell.addEventListener('transitionend', () => shell.remove(), { once: true });
  setTimeout(() => shell.remove(), 400);
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={base}>
      <ThemeProvider>
        <AuthProvider>
          <ToastProvider>
            <ErrorBoundary>
              <App onReady={dismissBootSkeleton} />
            </ErrorBoundary>
          </ToastProvider>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
