/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

const LiveContext = createContext(null);

const POLL_INTERVAL = 8000; // 8s — feels live without hammering the API

export const LiveProvider = ({ children }) => {
  const [refreshTick, setRefreshTick] = useState(0);
  const intervalRef = useRef(null);

  const tick = useCallback(() => {
    setRefreshTick((n) => n + 1);
  }, []);

  // Continuous polling
  useEffect(() => {
    intervalRef.current = setInterval(tick, POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, [tick]);

  // Also tick when the tab becomes visible again (user switches back)
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [tick]);

  return (
    <LiveContext.Provider value={{ refreshTick, tick }}>
      {children}
    </LiveContext.Provider>
  );
};

export const useLive = () => {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error('useLive must be used within LiveProvider');
  return ctx;
};