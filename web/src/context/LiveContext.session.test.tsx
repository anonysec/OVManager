// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * The live stream does its own fetch, so the api client's 401 handling never
 * sees it. Without an explicit reaction, a dead session leaves the operator
 * looking at a frozen dashboard while every action fails.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { LiveProvider } from './LiveContext';
import { AUTH_EXPIRED_EVENT } from '../services/api';

describe('the live stream when the session dies', () => {
  let expired = false;

  beforeEach(() => {
    expired = false;
    localStorage.setItem('userRole', 'owner');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      body: null,
      text: async () => '',
      headers: new Headers(),
    }));
    const onExpired = () => { expired = true; };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('ends the session when the stream answers 401', async () => {
    render(<LiveProvider><div>live</div></LiveProvider>);
    await waitFor(() => expect(expired).toBe(true));
  });
});
