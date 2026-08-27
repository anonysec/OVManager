// Copyright (c) 2025 anonysec. All rights reserved.
// Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { getUrlPath, getPanelBase, getPanelOrigin } from './panelUrl';

describe('panelUrl helpers', () => {
  let originalBase;

  beforeEach(() => {
    originalBase = document.querySelector('base');
    if (originalBase) originalBase.remove();
  });

  afterEach(() => {
    const existing = document.querySelector('base');
    if (existing) existing.remove();
    if (originalBase) document.head.appendChild(originalBase);
  });

  it('reads prefix from <base href="/dashboard/">', () => {
    const base = document.createElement('base');
    base.setAttribute('href', '/dashboard/');
    document.head.appendChild(base);

    expect(getUrlPath()).toBe('dashboard');
    expect(getPanelBase()).toBe('/dashboard');
    expect(getPanelOrigin()).toBe(`${window.location.origin}/dashboard`);
  });

  it('returns empty string when <base href="/">', () => {
    const base = document.createElement('base');
    base.setAttribute('href', '/');
    document.head.appendChild(base);

    expect(getUrlPath()).toBe('');
    expect(getPanelBase()).toBe('');
    expect(getPanelOrigin()).toBe(window.location.origin);
  });

  it('defaults to root when no <base> tag on normal host', () => {
    expect(getUrlPath()).toBe('');
    expect(getPanelBase()).toBe('');
    expect(getPanelOrigin()).toBe(window.location.origin);
  });

  it('derives repo subpath on *.github.io without <base> tag', () => {
    const originalLocation = window.location;
    delete window.location;
    window.location = {
      origin: 'https://anonysec.github.io',
      hostname: 'anonysec.github.io',
      pathname: '/OVManager/login',
    };

    try {
      expect(getUrlPath()).toBe('OVManager');
      expect(getPanelBase()).toBe('/OVManager');
      expect(getPanelOrigin()).toBe('https://anonysec.github.io/OVManager');
    } finally {
      window.location = originalLocation;
    }
  });
});
