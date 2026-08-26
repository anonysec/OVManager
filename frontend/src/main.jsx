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

/**
 * Remove the static app-shell skeleton from index.html.
 *
 * Called from the root render callback, so it only runs once React has
 * actually committed real content — swapping any earlier would show a blank
 * frame. Fades out to avoid a hard cut between shell and app.
 */
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
  // Match the transition; `once` so the node is only removed a single time.
  shell.addEventListener('transitionend', () => shell.remove(), { once: true });
  // Belt and braces: if the transition never fires (tab backgrounded), clean up.
  setTimeout(() => shell.remove(), 400);
}

ReactDOM.createRoot(document.getElementById('root')).render(
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
