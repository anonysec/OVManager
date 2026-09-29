/** Flag chip for a country code. Data lives in ./geo.js so non-component
 *  consumers can import it without pulling in React. */
import { FLAG_SVGS } from './geo.js';

const FlagIcon = ({ code }: { code?: any }) => {
  // No invented flags: unknown/missing codes render nothing (the label
  // already says "Location unavailable"). Defaulting to DE here once
  // showed a German flag next to wrong data.
  const flags = FLAG_SVGS as Record<string, string>;
  if (!code || !flags[code]) return null;
  return (
    <span className="flag-icon" dangerouslySetInnerHTML={{ __html: flags[code] }} />
  );
};

export default FlagIcon;
export { FlagIcon };
