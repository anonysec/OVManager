import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import UserTable from './UserTable';

/**
 * Sortable headers were plain `<th onClick>`: unreachable by keyboard and
 * silent to screen readers. These lock in the fix.
 */
const users = [
  { uuid: 'a', name: 'alice', is_active: true, total: 100, used: 10, max_logins: 2, owner: 'root' },
  { uuid: 'b', name: 'bob', is_active: true, total: 200, used: 20, max_logins: 1, owner: 'root' },
];

const noop = () => {};

/** Headers that opted into sorting (plain <th> have no aria-sort at all). */
const sortableHeaders = (screenRef) =>
  screenRef.getAllByRole('columnheader').filter((th) => th.hasAttribute('aria-sort'));
const activeHeader = (screenRef) =>
  sortableHeaders(screenRef).find((th) => th.getAttribute('aria-sort') !== 'none');

function setup(props = {}) {
  const onSort = vi.fn();
  render(
    <MemoryRouter>
      <UserTable
        users={users}
        selected={[]}
        onSelectAll={noop}
        onSelectOne={noop}
        sort={{ key: 'name', dir: 'asc' }}
        onSort={onSort}
        onEdit={noop}
        onDelete={noop}
        {...props}
      />
    </MemoryRouter>,
  );
  return { onSort };
}

describe('UserTable sortable headers', () => {
  it('exposes aria-sort reflecting the active column and direction', () => {
    setup();
    const active = activeHeader(screen);
    expect(active, 'expected one column to report a sort state').toBeTruthy();
    expect(active.getAttribute('aria-sort')).toBe('ascending');
  });

  it('flips the announced direction when sort.dir is desc', () => {
    setup({ sort: { key: 'name', dir: 'desc' } });
    const active = activeHeader(screen);
    expect(active, 'expected one column to report a sort state').toBeTruthy();
    expect(active.getAttribute('aria-sort')).toBe('descending');
  });

  it('marks non-active sortable columns as aria-sort="none"', () => {
    setup();
    const sortables = sortableHeaders(screen);
    expect(sortables.length).toBeGreaterThan(1);
    expect(sortables.filter((th) => th.getAttribute('aria-sort') === 'none').length).toBe(sortables.length - 1);
  });

  it('is focusable and activates like a button, not just on mouse click', () => {
    const { onSort } = setup();
    const btn = screen.getAllByRole('button').find((b) => b.className.includes('th-sort-btn'));
    expect(btn, 'headers should render a real button').toBeTruthy();

    // A bare <th onClick> can never hold focus; a <button> can. This is the
    // property that made the column keyboard-operable.
    btn.focus();
    expect(document.activeElement).toBe(btn);
    expect(btn.tagName).toBe('BUTTON');

    // Enter/Space on a focused button dispatch a click natively.
    fireEvent.click(btn);
    expect(onSort).toHaveBeenCalledWith('name');
  });
});
