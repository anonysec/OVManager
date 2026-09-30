// Resolve several independent requests without letting one failure sink the
// rest; returns a keyed map of { data, error, ok }.
//
//   const r = await settle({ stats: api.get('/server/info'), users: api.get('/users/') });
//   r.stats.ok ? r.stats.data : renderStatsError(r.stats.error)
//
// Pages used to fan out with `Promise.all([...])`, which is all-or-nothing: a
// single 500 on `/security/summary` rendered the whole dashboard's error state
// even though stats, users and nodes all came back fine.

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
