/** Flag chip for a country code. Data lives in ./geo.js so non-component
 *  consumers can import it without pulling in React. */
import { FLAG_SVGS } from './geo.js';

const FlagIcon = ({ code }) => {
  // No invented flags: unknown/missing codes render nothing (the label
  // already says "Location unavailable"). Defaulting to DE here once
  // showed a German flag next to wrong data.
  if (!code || !FLAG_SVGS[code]) return null;
  return (
    <span className="flag-icon" dangerouslySetInnerHTML={{ __html: FLAG_SVGS[code] }} />
  );
};

export default FlagIcon;
export { FlagIcon };
