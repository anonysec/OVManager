// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/react';
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

describe('Modal optional onClose', () => {
  it('does not throw on Escape when onClose is omitted', () => {
    render(<Modal isOpen title="x" />);
    fireEvent.keyDown(document.querySelector('[role="dialog"]') as HTMLElement, { key: 'Escape' });
  });
});

describe('Modal backdrop dismiss', () => {
  const open = (onClose: () => void) => render(
    <Modal isOpen onClose={onClose}>
      <input id="name" defaultValue="" />
    </Modal>
  );

  afterEach(() => {
    cleanup();
    document.getElementById('modal-root')?.remove();
    document.body.style.overflow = '';
  });

  const backdropClick = (x = 10, y = 10) => {
    const backdrop = document.querySelector('.modal-backdrop') as HTMLElement;
    fireEvent.mouseDown(backdrop, { clientX: x, clientY: y });
    fireEvent.click(backdrop, { clientX: x, clientY: y });
  };

  it('closes on a plain backdrop click', () => {
    let closed = 0;
    open(() => { closed += 1; });
    backdropClick();
    expect(closed).toBe(1);
  });

  it('ignores a drag that ends on the backdrop', () => {
    let closed = 0;
    open(() => { closed += 1; });
    const backdrop = document.querySelector('.modal-backdrop') as HTMLElement;
    fireEvent.mouseDown(backdrop, { clientX: 10, clientY: 10 });
    fireEvent.click(backdrop, { clientX: 80, clientY: 80 });
    expect(closed).toBe(0);
  });

  it('does not close once the form has been edited', () => {
    let closed = 0;
    open(() => { closed += 1; });
    fireEvent.change(document.querySelector('#name') as HTMLElement, { target: { value: 'alice' } });
    backdropClick();
    expect(closed).toBe(0);
  });
});
