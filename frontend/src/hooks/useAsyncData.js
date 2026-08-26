import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Resolve several independent requests without letting one failure sink the
 * rest. Returns a keyed map of { data, error, ok }.
 *
 *   const r = await settle({ stats: api.get('/server/info'), users: api.get('/users/') });
 *   r.stats.ok ? r.stats.data : renderStatsError(r.stats.error)
 *
 * This is the core of the panel's per-section error handling. Pages used to
 * fan out with `Promise.all([...])`, which is all-or-nothing — if
 * `/security/summary` 500s the whole dashboard renders its error state even
 * though stats, users and nodes all came back fine.
 */
export async function settle(sources) {
  const keys = Object.keys(sources);
  const results = await Promise.allSettled(keys.map((k) => sources[k]));
  return keys.reduce((acc, key, i) => {
    const r = results[i];
    acc[key] = r.status === 'fulfilled'
      ? { data: r.value, error: null, ok: true }
      : { data: null, error: r.reason, ok: false };
    return acc;
  }, {});
}

/**
 * Single-source async state with the two loading modes that matter for
 * perceived speed:
 *
 *   - `loading`     first load, nothing to show yet  -> render a skeleton
 *   - `refreshing`  background refresh, data on screen -> keep the data,
 *                   show a subtle indicator, never flash a skeleton
 *
 * `fetcher` must be a stable reference (wrap it in useCallback), the same
 * contract as useEffect dependencies.
 */
export function useAsyncData(fetcher, { immediate = true } = {}) {
  const [state, setState] = useState({
    data: null,
    error: null,
    loading: immediate,
    refreshing: false,
    lastUpdated: null,
  });

  // Guards against setState-after-unmount and out-of-order responses: a slow
  // request that resolves after a newer one must not clobber fresher data.
  const mounted = useRef(true);
  const runId = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const run = useCallback(async ({ background = false } = {}) => {
    const id = ++runId.current;

    setState((s) => ({
      ...s,
      error: null,
      // Only show the skeleton when there is genuinely nothing to look at.
      loading: background ? s.loading : s.data === null,
      refreshing: background,
    }));

    try {
      const result = await fetcher();
      if (!mounted.current || id !== runId.current) return result;
      setState({
        data: result,
        error: null,
        loading: false,
        refreshing: false,
        lastUpdated: new Date(),
      });
      return result;
    } catch (err) {
      if (!mounted.current || id !== runId.current) return null;
      // Keep whatever data we already had: stale content plus an error beats
      // an empty screen.
      setState((s) => ({ ...s, error: err, loading: false, refreshing: false }));
      return null;
    }
  }, [fetcher]);

  useEffect(() => {
    if (immediate) run();
  }, [run, immediate]);

  const refresh = useCallback(() => run({ background: true }), [run]);
  const retry = useCallback(() => run({ background: false }), [run]);

  return {
    ...state,
    hasData: state.data !== null,
    run,
    refresh,
    retry,
  };
}

export default useAsyncData;
