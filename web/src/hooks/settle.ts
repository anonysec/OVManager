// Resolve several independent requests without letting one failure sink the
// rest; returns a keyed map of { data, error, ok }.
//

export type Settled<T> = {
  data: T | null;
  // `Promise.allSettled` types its rejection reason as `any`; rejections here
  // are arbitrary values, so the error field carries the same freedom.
  error: any;
  ok: boolean;
};

export async function settle<T extends Record<string, Promise<unknown>>>(
  sources: T,
): Promise<{ [K in keyof T]: Settled<Awaited<T[K]>> }> {
  const keys = Object.keys(sources) as (keyof T & string)[];
  const results = await Promise.allSettled(keys.map((k) => sources[k]));
  return keys.reduce((acc, key, i) => {
    const r = results[i];
    acc[key] = r.status === 'fulfilled'
      ? { data: r.value as Awaited<T[typeof key]>, error: null, ok: true }
      : { data: null, error: r.reason, ok: false };
    return acc;
  }, {} as { [K in keyof T]: Settled<Awaited<T[K]>> });
}
