const PanelSkeleton = ({ lines = 4, label = 'Loading' }) => (
  <div className="panel-skeleton" role="status" aria-busy="true" aria-label={label}>
    {Array.from({ length: lines }).map((_, i) => (
      <span key={i} className="skeleton-shimmer" style={{ width: `${92 - i * 10}%` }} />
    ))}
  </div>
);

export default PanelSkeleton;