// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useState, useEffect } from 'react';

const STORAGE_KEY = 'ovmanager-mask-ips';

/**
 * usePrivacyMask — hook to read the current IP-mask preference.
 * Falls back to true (masked) if no value is stored yet.
 */
export const usePrivacyMask = () => {
  const [maskIps, setMaskIps] = useState(true);
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    setMaskIps(saved === null ? true : saved === 'true');
  }, []);
  return maskIps;
};

export default usePrivacyMask;