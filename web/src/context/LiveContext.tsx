// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { apiBase, AUTH_EXPIRED_EVENT } from '../services/api';

const LiveContext = createContext<any>(null);

const POLL_INTERVAL = 8000; // fallback polling while the stream is down
const RECONNECT_MS = 20000; // SSE reconnect delay after a failure
const RETRY_WHEN_LOGGED_OUT_MS = 5000;


async function readEventStream(body: any, onEvent: any) {
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
      let topic = null;
      let data: any = null;
      for (const line of block.split('\n')) {
        const trimmed = line.trim();
        if (trimmed.startsWith('event:')) {
          topic = trimmed.slice(6).trim();
        } else if (trimmed.startsWith('data:')) {
          const raw = trimmed.slice(5).trim();
          try { data = JSON.parse(raw); } catch { data = raw; }
        }
      }
      onEvent(topic, data);
    }
  }
}

export const LiveProvider = ({ children }: { children?: any }) => {
  const [refreshTick, setRefreshTick] = useState(0);
  const [streamConnected, setStreamConnected] = useState(false);
  const abortRef = useRef<any>(null);

  const listenersRef = useRef<any>(new Map());
  const subscribe = useCallback((event: any, cb: any) => {
    if (!listenersRef.current.has(event)) listenersRef.current.set(event, new Set());
    listenersRef.current.get(event).add(cb);
    return () => {
      const set = listenersRef.current.get(event);
      if (set) set.delete(cb);
    };
  }, []);
  const unsubscribe = useCallback((event: any, cb: any) => {
    const set = listenersRef.current.get(event);
    if (set) set.delete(cb);
  }, []);
  const publish = useCallback((event: any) => {
    const set = listenersRef.current.get(event);
    if (set) set.forEach((cb: () => void) => cb());
  }, []);

  const tickWithPublish = useCallback((topic?: any) => {
    setRefreshTick((n) => n + 1);
    publish('tick');
    if (topic) {
      publish(topic);
      if (!topic.includes('.')) publish(`${topic}.changed`);
    }
  }, [publish]);

  useEffect(() => {
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined = undefined;

    const connect = async () => {
      if (stopped) return;
      // The stream authenticates with the session cookie. The role in
      // storage is only the "we believe there is a session" hint; the server
      // has the last word (a 401 fails the stream like any other error).
      if (!localStorage.getItem('userRole')) {
        retryTimer = setTimeout(connect, RETRY_WHEN_LOGGED_OUT_MS);
        return;
      }
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const resp = await fetch(`${apiBase}/live/stream`, {
          credentials: 'same-origin',
          signal: ctrl.signal,
        });
        if (resp.status === 401) {
          // The session died. The stream does its own fetch, so the api
          // client's 401 handling never sees it: without this the operator
          // is left looking at a frozen dashboard with every action
          // failing, and the stream retries forever.
          window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
          return;
        }
        if (!resp.ok || !resp.body) throw new Error(`live stream HTTP ${resp.status}`);
        if (!stopped) setStreamConnected(true);
        await readEventStream(resp.body, (topic: string | null, data?: any) => {
          void data;
          if (!stopped) tickWithPublish(topic);
        });
      } catch (e) { console.warn('live stream error', e); /* retry below */
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
  }, [tickWithPublish]);

  useEffect(() => {
    if (streamConnected) return undefined;
    const id = setInterval(tickWithPublish, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [streamConnected, tickWithPublish]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') tickWithPublish();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [tickWithPublish]);

  return (
    <LiveContext.Provider value={{ refreshTick, tick: tickWithPublish, streamConnected, subscribe, unsubscribe }}>
      {children}
    </LiveContext.Provider>
  );
};

export const useLive = () => {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error('useLive must be used within LiveProvider');
  return ctx;
};
