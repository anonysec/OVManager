// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useRef, useState, useCallback, useEffect } from 'react';

/**
 * usePullRefresh — pull-down-to-refresh for touch devices.
 *
 * Attach `onTouchStart` / `onTouchMove` / `onTouchEnd` to a container and
 * pass `ref` so we only trigger when the container is scrolled to the top.
 * Fires `onRefresh` once the pull exceeds the threshold, then shows a
 * transient "release" state via `pulling` / `refreshing`.
 */
export const usePullRefresh = (onRefresh, { threshold = 80 } = {}) => {
  const startY = useRef(null);
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  // Keep the current pull distance in a ref too: touch events fire faster
  // than React re-renders, so onTouchEnd must read the latest value, not a
  // stale closure.
  const pullRef = useRef(0);

  const onTouchStart = useCallback((e) => {
    if (refreshing) return;
    if ((e.currentTarget.scrollTop ?? window.scrollY) > 4) return;
    startY.current = e.touches[0].clientY;
  }, [refreshing]);

  const onTouchMove = useCallback((e) => {
    if (startY.current === null) return;
    const dy = e.touches[0].clientY - startY.current;
    if (dy > 0 && (e.currentTarget.scrollTop ?? window.scrollY) <= 4) {
      const next = Math.min(threshold * 1.6, dy);
      pullRef.current = next;
      setPull(next);
      if (dy > threshold) e.preventDefault();
    }
  }, [threshold]);

  const onTouchEnd = useCallback(() => {
    startY.current = null;
    const p = pullRef.current;
    pullRef.current = 0;
    setPull(0);
    if (p >= threshold) {
      setRefreshing(true);
      Promise.resolve(onRefresh && onRefresh()).finally(() => {
        setRefreshing(false);
      });
    }
  }, [threshold, onRefresh]);

  useEffect(() => {
    if (refreshing) {
      const id = setTimeout(() => setRefreshing(false), 8000); // safety
      return () => clearTimeout(id);
    }
  }, [refreshing]);

  return {
    pull,
    refreshing,
    onTouchStart,
    onTouchMove,
    onTouchEnd,
  };
};
