// Data lives in ./geo.js so non-component consumers can import it without
// pulling in React.
import { FLAG_SVGS } from './geo.js';

const FlagIcon = ({ code }: { code?: any }) => {
  // Unknown/missing codes render nothing: defaulting to DE here once showed a
  // German flag next to wrong data.
  const flags = FLAG_SVGS as Record<string, string>;
  if (!code || !flags[code]) return null;
  return (
    <span className="flag-icon" dangerouslySetInnerHTML={{ __html: flags[code] }} />
  );
};

export default FlagIcon;
export { FlagIcon };
