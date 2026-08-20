const UserStatCard = ({ icon, label, value, color, className }) => {
  return (
    <article className={`metric-card ${className || ''}`} style={{ '--metric-color': color || 'var(--accent-color)' }}>
      <div className="metric-icon">{icon}</div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </article>
  );
};

export default UserStatCard;
