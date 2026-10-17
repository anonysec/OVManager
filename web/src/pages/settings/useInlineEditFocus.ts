// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/* Focus management for inline editors: move focus into the input on open
   and return it to the invoking edit button on close. Plain module
   (no JSX) so it stays clear of the fast-refresh components-only rule. */
import { useRef, useEffect } from 'react';
import type { RefObject } from 'react';

const useInlineEditFocus = (
  editing: boolean,
  inputRef: RefObject<HTMLElement | null>,
  triggerRef: RefObject<HTMLElement | null>,
): void => {
  const wasOpen = useRef(false);
  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      wasOpen.current = true;
    } else if (wasOpen.current) {
      triggerRef.current?.focus();
      wasOpen.current = false;
    }
  }, [editing, inputRef, triggerRef]);
};

export default useInlineEditFocus;
