// Deliberately dependency-free and driven by plain CSS classes: these render
// in Suspense fallbacks on the critical path, so they must not drag extra
// modules into the entry chunk.
//
// Accessibility: the primitives are decorative and hidden from assistive tech.
// The *container* owns a single polite live region, so a screen reader hears
// "Loading" once instead of narrating a dozen grey boxes.

import type { CSSProperties } from 'react';

type SkeletonBlockProps = {
  width?: any;
  height?: number;
  radius?: number;
  className?: string;
  style?: CSSProperties;
};

export const SkeletonBlock = ({ width, height = 14, radius = 6, className = '', style }: SkeletonBlockProps) => (
  <span
    className={`sk-block ${className}`}
    aria-hidden="true"
    style={{ width, height, borderRadius: radius, ...style }}
  />
);

export const SkeletonText = ({ lines = 3, width = '100%' }: { lines?: number; width?: any }) => (
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

// Matches .ops-panel geometry on the dashboard.
export const SkeletonPanel = ({ lines = 3, label = 'Loading', height }: { lines?: number; label?: any; height?: any }) => (
  <div className="sk-panel" role="status" aria-live="polite" aria-label={label} style={height ? { minHeight: height } : undefined}>
    <SkeletonText lines={lines} />
  </div>
);

export const SkeletonStats = ({ count = 4, label = 'Loading' }: { count?: number; label?: any }) => (
  <div className="sk-stats" role="status" aria-live="polite" aria-label={label}>
    {Array.from({ length: count }, (_, i) => (
      <div className="sk-stat" key={i}>
        <SkeletonBlock width="52%" height={11} />
        <SkeletonBlock width="72%" height={26} radius={8} />
      </div>
    ))}
  </div>
);

// Mirrors the real column count so the layout does not jump when rows arrive.
export const SkeletonTable = ({ rows = 8, cols = 9, label = 'Loading' }: { rows?: number; cols?: number; label?: any }) => (
  <div className="sk-table" role="status" aria-live="polite" aria-label={label} style={{ '--sk-cols': cols } as any}>
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
