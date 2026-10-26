// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import '../i18n';
import Modal from './Modal';

describe('Modal inert attribute cleanup', () => {
  afterEach(() => {
    cleanup();
    document.getElementById('modal-root')?.remove();
    document.getElementById('root')?.remove();
    document.body.style.overflow = '';
  });

  it('restores inert when closed so root is clickable', () => {
    const root = document.createElement('div');
    root.id = 'root';
    document.body.appendChild(root);

    const { rerender } = render(
      <Modal isOpen={true} onClose={() => {}}>
        <div>Modal Content</div>
      </Modal>
    );

    expect(root.hasAttribute('inert')).toBe(true);

    rerender(
      <Modal isOpen={false} onClose={() => {}}>
        <div>Modal Content</div>
      </Modal>
    );

    expect(root.hasAttribute('inert')).toBe(false);
  });
});
