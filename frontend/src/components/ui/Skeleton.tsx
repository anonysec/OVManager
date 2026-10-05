// Deliberately dependency-free and driven by plain CSS classes: these render
// in Suspense fallbacks on the critical path, so they must not drag extra
// modules into the entry chunk.

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
        width={i === lines - 1 ? '62%' : width}
      />
    ))}
  </span>
);

export const SkeletonPanel = ({ lines = 3, label = 'Loading', height }: { lines?: number; label?: any; height?: any }) => (
  <div className="sk-panel" role="status" aria-live="polite" aria-label={label} style={height ? { minHeight: height } : undefined}>
    <SkeletonText lines={lines} />
  </div>
);

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
