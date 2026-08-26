/**
 * Skeleton primitives.
 *
 * Deliberately dependency-free and driven by plain CSS classes so these can be
 * rendered by Suspense fallbacks in the critical path without dragging extra
 * modules into the entry chunk.
 *
 * Accessibility: skeletons are decorative placeholders. They are hidden from
 * assistive tech and the *container* owns a single polite live region, so a
 * screen reader hears "Loading" once instead of narrating a dozen grey boxes.
 */

export const SkeletonBlock = ({ width, height = 14, radius = 6, className = '', style }) => (
  <span
    className={`sk-block ${className}`}
    aria-hidden="true"
    style={{ width, height, borderRadius: radius, ...style }}
  />
);

export const SkeletonText = ({ lines = 3, width = '100%' }) => (
  <span className="sk-text" aria-hidden="true">
    {Array.from({ length: lines }, (_, i) => (
      <SkeletonBlock
        key={i}
        // Taper the last line so the block reads as prose, not a solid slab.
        width={i === lines - 1 ? '62%' : width}
      />
    ))}
  </span>
);

/** Panel-shaped placeholder: matches .ops-panel geometry on the dashboard. */
export const SkeletonPanel = ({ lines = 3, label = 'Loading', height }) => (
  <div className="sk-panel" role="status" aria-live="polite" aria-label={label} style={height ? { minHeight: height } : undefined}>
    <SkeletonText lines={lines} />
  </div>
);

/** Stat-grid placeholder used inside dashboard panels. */
export const SkeletonStats = ({ count = 4, label = 'Loading' }) => (
  <div className="sk-stats" role="status" aria-live="polite" aria-label={label}>
    {Array.from({ length: count }, (_, i) => (
      <div className="sk-stat" key={i}>
        <SkeletonBlock width="52%" height={11} />
        <SkeletonBlock width="72%" height={26} radius={8} />
      </div>
    ))}
  </div>
);

/**
 * Table placeholder. Mirrors the real column count so the layout does not jump
 * when rows arrive — the main cause of perceived "flashing" on refresh.
 */
export const SkeletonTable = ({ rows = 8, cols = 9, label = 'Loading' }) => (
  <div className="sk-table" role="status" aria-live="polite" aria-label={label} style={{ '--sk-cols': cols }}>
    <div className="sk-table-head" aria-hidden="true">
      {Array.from({ length: cols }, (_, i) => (
        <SkeletonBlock key={i} height={10} width={i === 0 ? '70%' : '45%'} />
      ))}
    </div>
    {Array.from({ length: rows }, (_, r) => (
      <div className="sk-table-row" key={r} aria-hidden="true">
        {Array.from({ length: cols }, (_, c) => (
          <SkeletonBlock key={c} height={12} width={c === 0 ? '80%' : c === cols - 1 ? '40%' : '55%'} />
        ))}
      </div>
    ))}
  </div>
);

export default SkeletonBlock;
