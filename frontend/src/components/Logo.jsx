/**
 * OVManager logo. The accent colour is driven by `currentColor`, so callers
 * can drop the logo in any context and recolour it via `color: var(--accent)`
 * (or any other token). The dark inner detail uses a CSS variable that
 * resolves to the same dark ink in both light and dark themes.
 *
 * The globe is deliberately minimal (ring + meridian + equator + hub) so it
 * stays legible at 38px and below — finer detail turned to mud at menu size.
 */
const Logo = ({ size = 38, className = '' }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    className={`ops-logo-svg ${className}`}
    role="img"
    aria-label="OVManager"
    style={{ color: 'var(--accent-color, var(--accent, #ff7a1e))' }}
  >
    <rect x="2" y="2" width="44" height="44" rx="13" fill="currentColor" />
    <circle cx="24" cy="24" r="12.5" fill="none" stroke="var(--logo-ink, #15110a)" strokeWidth="3" />
    <ellipse cx="24" cy="24" rx="5.5" ry="12.5" fill="none" stroke="var(--logo-ink, #15110a)" strokeWidth="2.2" />
    <line x1="11.5" y1="24" x2="36.5" y2="24" stroke="var(--logo-ink, #15110a)" strokeWidth="2.2" />
    <circle cx="24" cy="24" r="3.6" fill="var(--logo-ink, #15110a)" />
  </svg>
);

export default Logo;
