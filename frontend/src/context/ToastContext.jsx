/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useCallback } from 'react';

const ToastContext = createContext();

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
};

// Human-readable label + icon for each toast level.
const TOAST_LABELS = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, status = 'success', duration = 3500) => {
    const id = Date.now() + Math.random();
    const normalizedStatus = String(status || 'success').toLowerCase();
    setToasts((prev) => [...prev, { id, message, status: normalizedStatus }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, duration);
  }, []);

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="toast-stack" role="region" aria-label="Notifications" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => (
          <div className={`toast toast-${toast.status}`} key={toast.id} role="alert">
            {/* Icon prefix instead of raw status string */}
            <strong aria-hidden="true">{TOAST_LABELS[toast.status] || '•'}</strong>
            <span>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};
