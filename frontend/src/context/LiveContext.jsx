// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { apiBase } from '../services/api';

const LiveContext = createContext(null);

const POLL_INTERVAL = 8000; // fallback polling while the stream is down
const RECONNECT_MS = 20000; // SSE reconnect delay after a failure
const RETRY_WHEN_LOGGED_OUT_MS = 5000;

/**
 * Minimal SSE reader over fetch(). The native EventSource API can't set an
 * Authorization header (this panel authenticates with Bearer tokens), so we
 * parse the text/event-stream wire format ourselves — it's just
 * "event:/data:" lines separated by blank lines, with ":..." heartbeat
 * comments to ignore.
 */
async function readEventStream(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (!block || block.startsWith(':')) continue; // heartbeat / comment
      onEvent();
    }
  }
}

export const LiveProvider = ({ children }) => {
  // refreshTick is the public contract: any change notifies consumers to
  // refetch. The transport behind it is SSE with transparent fallback to
  // 8s polling — consumers never know the difference.
  const [refreshTick, setRefreshTick] = useState(0);
  const [streamConnected, setStreamConnected] = useState(false);
  const tick = useCallback(() => setRefreshTick((n) => n + 1), []);
  const abortRef = useRef(null);

  // ── SSE transport ───────────────────────────────────────────────────
  // The backend pushes lightweight invalidation events (users/usage/nodes);
  // each one triggers the same refetch the old 8s interval did.
  useEffect(() => {
    let stopped = false;
    let retryTimer = null;

    const connect = async () => {
      if (stopped) return;
      const token = localStorage.getItem('authToken');
      if (!token) {
        // Logged out (provider still mounted e.g. during redirect): stay
        // quiet and retry shortly — a fresh login will have set a token.
        retryTimer = setTimeout(connect, RETRY_WHEN_LOGGED_OUT_MS);
        return;
      }
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const resp = await fetch(`${apiBase}/live/stream`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        });
        if (!resp.ok || !resp.body) throw new Error(`live stream HTTP ${resp.status}`);
        if (!stopped) setStreamConnected(true);
        // Blocks until the stream ends or the server disappears.
        await readEventStream(resp.body, () => {
          if (!stopped) tick();
        });
      } catch {
        // Network failure, aborted (logout/unmount), or 401 — retry below.
      }
      if (stopped) return;
      setStreamConnected(false);
      retryTimer = setTimeout(connect, RECONNECT_MS);
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      abortRef.current?.abort(); // closes the in-flight stream read
    };
  }, [tick]);

  // ── Polling fallback ──────────────────────────────────────────────────
  // Only active while the SSE stream is unavailable (proxy buffering, older
  // browser, backend without the live router). Zero double-polling otherwise.
  useEffect(() => {
    if (streamConnected) return undefined;
    const id = setInterval(tick, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [streamConnected, tick]);

  // Refresh when the user switches back to the tab (immediate, cheap).
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [tick]);

  return (
    <LiveContext.Provider value={{ refreshTick, tick, streamConnected }}>
      {children}
    </LiveContext.Provider>
  );
};

export const useLive = () => {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error('useLive must be used within LiveProvider');
  return ctx;
};
