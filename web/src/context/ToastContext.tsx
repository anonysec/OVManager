/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback, useRef } from 'react';

const ToastContext = createContext<any>(null);

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
};

const TOAST_LABELS: Record<string, string> = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
};

const DEFAULT_DURATION: Record<string, number | null> = {
  success: 3500,
  info: 3500,
  warning: 5000,
  error: null, // persist until dismissed — a vanishing error is a lost error
};

export const ToastProvider = ({ children }: { children?: any }) => {
  const [toasts, setToasts] = useState<any[]>([]);
  const timers = useRef<any>(new Map());

  const removeToast = useCallback((id: any) => {
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const schedule = useCallback((id: any, ms: any) => {
    if (!ms) return;
    const existing = timers.current.get(id);
    if (existing) clearTimeout(existing);
    timers.current.set(id, setTimeout(() => removeToast(id), ms));
  }, [removeToast]);

  const addToast = useCallback((message: any, status: any = 'success', duration?: any) => {
    const id = Date.now() + Math.random();
    const normalizedStatus = String(status || 'success').toLowerCase();
    const ms = duration === undefined ? DEFAULT_DURATION[normalizedStatus] : duration;
    setToasts((prev) => [...prev.slice(-4), { id, message, status: normalizedStatus, duration: ms }]);
    schedule(id, ms);
  }, [schedule]);

  const pause = (id: any) => {
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
  };

  const resume = (toast: any) => {
    if (toast.duration) schedule(toast.id, toast.duration);
  };

  return (
    <ToastContext.Provider value={{ addToast, removeToast }}>
      {children}
      <div className="toast-stack" role="region" aria-label="Notifications">
        {toasts.map((toast) => (
          <div
            className={`toast toast-${toast.status}`}
            key={toast.id}
            role={toast.status === 'error' ? 'alert' : 'status'}
            aria-live={toast.status === 'error' ? 'assertive' : 'polite'}
            onMouseEnter={() => pause(toast.id)}
            onMouseLeave={() => resume(toast)}
          >
            <strong aria-hidden="true">{TOAST_LABELS[toast.status] || '•'}</strong>
            <span>{toast.message}</span>
            <button
              type="button"
              className="toast-dismiss"
              onClick={() => removeToast(toast.id)}
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};
