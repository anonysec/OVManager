// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../i18n';
import { ToastProvider } from './ToastContext';

const fire = (message: string, transient: boolean) => {
  act(() => {
    window.dispatchEvent(new CustomEvent('api:error', {
      detail: { status: transient ? 0 : 500, message, url: '/x', transient },
    }));
  });
};

describe('ToastProvider network errors', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('auto-dismisses a transient network error', () => {
    render(<ToastProvider><div /></ToastProvider>);
    fire('Failed to fetch', true);
    expect(screen.getByText('Failed to fetch')).toBeTruthy();
    act(() => { vi.advanceTimersByTime(8001); });
    expect(screen.queryByText('Failed to fetch')).toBeNull();
  });

  it('coalesces repeated network errors into one toast', () => {
    render(<ToastProvider><div /></ToastProvider>);
    fire('Failed to fetch', true);
    fire('NetworkError', true);
    fire('Failed to fetch', true);
    expect(screen.getAllByText(/Failed to fetch|NetworkError/)).toHaveLength(1);
  });

  it('keeps a real server error until dismissed', () => {
    render(<ToastProvider><div /></ToastProvider>);
    fire('Could not save', false);
    act(() => { vi.advanceTimersByTime(60000); });
    expect(screen.getByText('Could not save')).toBeTruthy();
  });
});
