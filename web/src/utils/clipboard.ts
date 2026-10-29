// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

export async function copyText(text: unknown): Promise<boolean> {
  if (text == null) return false;
  const value = String(text);
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    /* fall through to legacy path */
  }
  const ta = document.createElement('textarea');
  ta.value = value;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.top = '-2000px';
  ta.style.left = '-2000px';
  ta.style.opacity = '0';
  try {
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, value.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    if (ta.parentNode) ta.parentNode.removeChild(ta);
  }
}
