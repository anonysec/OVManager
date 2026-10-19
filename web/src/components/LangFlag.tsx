// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import type { FC } from 'react';

const FaFlagIcon: FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <rect width="24" height="8" y="0" fill="#239f40" />
    <rect width="24" height="8" y="8" fill="#fff" />
    <rect width="24" height="8" y="16" fill="#da0000" />
    <g transform="translate(12,12)">
      <circle r="3.2" fill="#f4d35e" stroke="#b8860b" strokeWidth="0.4" />
      <path d="M-1.2,-1.6 Q0,-3.4 1.2,-1.6 L1.6,1.8 Q0,2.6 -1.6,1.8 Z" fill="#b8860b" />
      <path d="M-2.4,0.6 Q-3.6,-0.8 -2.8,-2.2" stroke="#b8860b" strokeWidth="0.5" fill="none" />
      <path d="M2.4,0.6 Q3.6,-0.8 2.8,-2.2" stroke="#b8860b" strokeWidth="0.5" fill="none" />
    </g>
  </svg>
);

const EnFlagIcon: FC = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <rect width="24" height="24" fill="#fff" />
    {Array.from({ length: 13 }).map((_, i) => (
      <rect key={i} y={i * (24 / 13)} width="24" height={24 / 13} fill={i % 2 === 0 ? '#b22234' : '#fff'} />
    ))}
    <rect width="10" height={24 * 7 / 13} fill="#3c3b6e" />
    {Array.from({ length: 50 }).map((_, i) => {
      const row = Math.floor(i / 11);
      const col = i % 11 - (row % 2 ? 0.5 : 0);
      return <circle key={i} cx={0.9 + col * (10 / 11)} cy={0.9 + row * (24 * 7 / 13 / 10)} r="0.45" fill="#fff" />;
    })}
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
