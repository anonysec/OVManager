// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * useEventSource — auto-reconnecting SSE hook.
 *
 * Falls back to a polling callback when EventSource is not available
 * (e.g. older browsers, test envs without native EventSource). The
 * fallback receives the URL just like the caller wants; polling is the
 * caller's responsibility so the data shape stays in one place.
 */
import { useEffect, useRef, useState } from 'react';

export default function useEventSource(url, { onMessage, onError, onOpen, enabled = true, withCredentials = false } = {}) {
  const [status, setStatus] = useState('idle'); // idle | connecting | open | error | closed
  const [lastError, setLastError] = useState(null);
  const handlerRef = useRef(onMessage);
  const errRef = useRef(onError);
  const openRef = useRef(onOpen);

  useEffect(() => { handlerRef.current = onMessage; }, [onMessage]);
  useEffect(() => { errRef.current = onError; }, [onError]);
  useEffect(() => { openRef.current = onOpen; }, [onOpen]);

  useEffect(() => {
    if (!enabled || !url || typeof window === 'undefined' || typeof window.EventSource === 'undefined') {
      setStatus('closed');
      return undefined;
    }

    let es;
    let retryTimer = null;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      if (closed) return;
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting');
      try {
        es = new EventSource(url, { withCredentials });
      } catch (e) {
        setLastError(e);
        setStatus('error');
        scheduleRetry();
        return;
      }
      es.onopen = () => {
        attempt = 0;
        setStatus('open');
        setLastError(null);
        if (openRef.current) openRef.current();
      };
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (handlerRef.current) handlerRef.current(data);
        } catch (e) {
          setLastError(e);
        }
      };
      es.onerror = () => {
        if (closed) return;
        setLastError(new Error('SSE connection error'));
        setStatus('error');
        if (errRef.current) errRef.current(new Error('SSE connection error'));
        try { es.close(); } catch { /* noop */ }
        scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      attempt += 1;
      const delay = Math.min(15000, 1000 * Math.pow(2, Math.min(attempt, 4)));
      retryTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (es) try { es.close(); } catch { /* noop */ }
      setStatus('closed');
    };
  }, [url, enabled, withCredentials]);

  return { status, lastError };
}
