/**
 * Geo helpers + flag SVGs shared by the dashboard map and the node list.
 * Extracted from ServerStats so the map chunk and the page can both use them
 * without the page pulling in d3-geo/world-atlas.
 */

const CODES = {
  DE: { name: 'Germany', coords: [10.4, 51.1] },
  TR: { name: 'Turkey', coords: [35.2, 39.1] },
  FI: { name: 'Finland', coords: [25.7, 61.9] },
  FR: { name: 'France', coords: [2.2, 46.6] },
  NL: { name: 'Netherlands', coords: [5.3, 52.1] },
  USA: { name: 'USA', coords: [-98.5, 39.8] },
  AE: { name: 'UAE', coords: [54, 24] },
  RU: { name: 'Russia', coords: [90, 61.5] },
  GB: { name: 'UK', coords: [-1.5, 52.5] },
  CA: { name: 'Canada', coords: [-106, 56] },
  SG: { name: 'Singapore', coords: [103.8, 1.35] },
  JP: { name: 'Japan', coords: [138, 36] },
};

const FLAG_SVGS = {
  DE: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#ffce00"/><rect width="640" height="160" fill="#000"/><rect y="320" width="640" height="160" fill="#d00"/></svg>',
  TR: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#e30a0a"/><circle cx="220" cy="240" r="70" fill="#fff"/><circle cx="220" cy="240" r="30" fill="#e30a0a"/></svg>',
  FI: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#fff"/><rect x="213" width="54" height="480" fill="#003897"/><rect y="213" width="640" height="54" fill="#003897"/></svg>',
  FR: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="213" height="480" fill="#002395"/><rect x="213" width="214" height="480" fill="#fff"/><rect x="427" width="213" height="480" fill="#ef4135"/></svg>',
  NL: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="160" fill="#ae1c28"/><rect y="160" width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#21468b"/></svg>',
  USA: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#b22234"/><rect width="640" height="80" fill="#fff"/><rect width="640" height="80" y="400" fill="#fff"/><rect width="640" height="80" y="80" fill="#fff"/><rect width="640" height="80" y="320" fill="#fff"/><g fill="#fff"><rect x="0" y="0" width="80" height="80"/><rect x="160" y="0" width="80" height="80"/><rect x="320" y="0" width="80" height="80"/><rect x="480" y="0" width="80" height="80"/><rect x="80" y="80" width="80" height="80"/><rect x="240" y="80" width="80" height="80"/><rect x="400" y="80" width="80" height="80"/><rect x="0" y="160" width="80" height="80"/><rect x="160" y="160" width="80" height="80"/><rect x="320" y="160" width="80" height="80"/><rect x="480" y="160" width="80" height="80"/><rect x="80" y="240" width="80" height="80"/><rect x="240" y="240" width="80" height="80"/><rect x="400" y="240" width="80" height="80"/><rect x="0" y="320" width="80" height="80"/><rect x="160" y="320" width="80" height="80"/><rect x="320" y="320" width="80" height="80"/><rect x="480" y="320" width="80" height="80"/></g></svg>',
  AE: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#00732f"/><rect y="160" width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#000"/><rect width="160" height="480" fill="#ce1126"/></svg>',
  RU: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="160" fill="#fff"/><rect y="160" width="640" height="160" fill="#0039a6"/><rect y="320" width="640" height="160" fill="#d52b1e"/></svg>',
  GB: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#012169"/><path d="M0 0L640 480M640 0L0 480" stroke="#fff" stroke-width="40"/><path d="M320 0v480M0 240h640" stroke="#fff" stroke-width="20"/><path d="M0 0l240 240M0 240l240 0M400 0l240 240M400 240l240 0" stroke="#c8102e" stroke-width="20"/></svg>',
  CA: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#ff0000"/><rect width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#fff"/><rect x="240" y="160" width="160" height="160" fill="#ff0000"/><circle cx="320" cy="240" r="40" fill="#fff"/></svg>',
  SG: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#ed2939"/><rect width="640" height="160" fill="#fff"/><rect y="320" width="640" height="160" fill="#fff"/><circle cx="320" cy="240" r="40" fill="#000"/><circle cx="320" cy="240" r="20" fill="#fff"/></svg>',
  JP: '<svg viewBox="0 0 640 480" width="20" height="15"><rect width="640" height="480" fill="#fff"/><circle cx="320" cy="240" r="80" fill="#bc002d"/></svg>',
};

const COUNTRY_ALIASES = {
  FL: 'FI',
  UK: 'GB',
  US: 'USA',
  UNITEDSTATES: 'USA',
  UAE: 'AE',
  UNITEDARABEMIRATES: 'AE',
};

const normalizeCountryCode = (node) => {
  // ONLY the stored ISO code from the backend counts. Never guess from the
  // node name — fuzzy matching once turned "node-1" into Netherlands
  // (lowercase-stripped names matched country initials).
  const raw = String(node?.country_code || '').trim().toUpperCase();
  if (!raw) return null;
  if (CODES[raw]) return raw;
  if (COUNTRY_ALIASES[raw] && CODES[COUNTRY_ALIASES[raw]]) return COUNTRY_ALIASES[raw];
  // Unknown-but-plausible ISO code: show the code text, no flag.
  return /^[A-Z]{2,3}$/.test(raw) ? raw : null;
};

const nodeMeta = (node) => {
  const latitude = Number(node.latitude);
  const longitude = Number(node.longitude);
  const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude)
    && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
    && !(latitude === 0 && longitude === 0);
  const code = normalizeCountryCode(node);
  const entry = code ? CODES[code] : null;

  return {
    name: entry?.name || (code || 'Location unavailable'),
    flagCode: entry ? code : null,
    coords: hasCoordinates ? [longitude, latitude] : (entry?.coords || null),
    approximate: !hasCoordinates && Boolean(entry?.coords),
  };
};


export { CODES, FLAG_SVGS, COUNTRY_ALIASES, normalizeCountryCode, nodeMeta };
