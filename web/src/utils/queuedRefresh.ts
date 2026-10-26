// Serialize repeated refresh triggers without dropping the latest invalidation.
// A caller arriving during an in-flight load queues one trailing pass; bursts
// collapse to the most recent arguments. This matters when API-level GET
// deduplication would otherwise hand an event-triggered caller an older promise.
export const createQueuedRefresh = <Args extends unknown[]>(
  work: (...args: Args) => void | Promise<void>,
) => {
  let active: Promise<void> | null = null;
  let queued: Args | null = null;

  const refresh = (...args: Args): Promise<void> => {
    if (active) {
      queued = args;
      return active;
    }

    const current = Promise.resolve().then(async () => {
      let nextArgs: Args | null = args;
      while (nextArgs) {
        queued = null;
        await work(...nextArgs);
        nextArgs = queued;
      }
    });
    active = current;

    const finish = () => {
      if (active !== current) return;
      active = null;
      // If a trigger arrived after the loop's last check but before this
      // promise's settlement handler, preserve it as a new refresh pass.
      if (queued) {
        const nextArgs = queued;
        queued = null;
        void refresh(...nextArgs);
      }
    };
    void current.then(finish, finish);
    return current;
  };

  return refresh;
};
