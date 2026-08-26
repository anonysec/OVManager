/** Flag chip for a country code. Data lives in ./geo.js so non-component
 *  consumers can import it without pulling in React. */
import { FLAG_SVGS } from './geo.js';

const FlagIcon = ({ code }) => (
  <span className="flag-icon" dangerouslySetInnerHTML={{ __html: FLAG_SVGS[code] || FLAG_SVGS.DE }} />
);

export default FlagIcon;
export { FlagIcon };
