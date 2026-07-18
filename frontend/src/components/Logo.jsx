const Logo = ({ size = 38, className = '' }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    className={`ops-logo-svg ${className}`}
    role="img"
    aria-label="OVManager"
  >
    <defs>
      <linearGradient id="ovLogoGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#ff7a1e" />
        <stop offset="1" stopColor="#ffb466" />
      </linearGradient>
    </defs>
    <rect x="2" y="2" width="44" height="44" rx="13" fill="url(#ovLogoGrad)" />
    <circle cx="24" cy="24" r="13" fill="none" stroke="#15110a" strokeWidth="2.2" opacity="0.85" />
    <ellipse cx="24" cy="24" rx="6" ry="13" fill="none" stroke="#15110a" strokeWidth="1.5" opacity="0.55" />
    <line x1="11" y1="24" x2="37" y2="24" stroke="#15110a" strokeWidth="1.5" opacity="0.55" />
    <line x1="15.5" y1="15.5" x2="32.5" y2="32.5" stroke="#15110a" strokeWidth="1.2" opacity="0.4" />
    <line x1="32.5" y1="15.5" x2="15.5" y2="32.5" stroke="#15110a" strokeWidth="1.2" opacity="0.4" />
    <circle cx="24" cy="24" r="3.1" fill="#15110a" />
    <circle cx="33.5" cy="16.5" r="2.7" fill="#15110a" />
    <circle cx="15" cy="31.5" r="2.7" fill="#15110a" />
    <line x1="24" y1="24" x2="33.5" y2="16.5" stroke="#15110a" strokeWidth="1.5" opacity="0.7" />
    <line x1="24" y1="24" x2="15" y2="31.5" stroke="#15110a" strokeWidth="1.5" opacity="0.7" />
  </svg>
);

export default Logo;
