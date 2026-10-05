// Resolve several independent requests without letting one failure sink the
// rest; returns a keyed map of { data, error, ok }.
//

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
