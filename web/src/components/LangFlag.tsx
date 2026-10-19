// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import type { FC } from 'react';

const FaFlagIcon: FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <rect width="24" height="8" y="0" fill="#239f40" />
    <rect width="24" height="8" y="8" fill="#fff" />
    <rect width="24" height="8" y="16" fill="#da0000" />
  </svg>
);

const EnFlagIcon: FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <rect width="24" height="24" fill="#fff" />
    <rect width="24" height="2.4" y="0" fill="#b22234" />
    <rect width="24" height="2.4" y="4.8" fill="#b22234" />
    <rect width="24" height="2.4" y="9.6" fill="#b22234" />
    <rect width="24" height="2.4" y="19.2" fill="#b22234" />
    <rect width="11" height="13" x="0" y="0" fill="#3c3b6e" />
  </svg>
);

const RuFlagIcon: FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <rect width="24" height="8" y="0" fill="#fff" />
    <rect width="24" height="8" y="8" fill="#0039a6" />
    <rect width="24" height="8" y="16" fill="#da291c" />
  </svg>
);

const CnFlagIcon: FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <rect width="24" height="24" fill="#de2910" />
    <polygon points="5,4 6.2,7.2 9.6,7.2 6.8,9.2 7.8,12.4 5,10.3 2.2,12.4 3.2,9.2 0.4,7.2 3.8,7.2" fill="#ffde00" />
  </svg>
);

const FLAGS: Record<string, FC> = { fa: FaFlagIcon, en: EnFlagIcon, ru: RuFlagIcon, cn: CnFlagIcon };

export const LangFlag: FC<{ code: string }> = ({ code }) => {
  const Flag = FLAGS[code];
  return Flag ? <Flag /> : null;
};
