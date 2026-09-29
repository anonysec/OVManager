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

export default settle;
