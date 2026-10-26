// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import '../i18n';
import UserSessionsModal from './UserSessionsModal';

afterEach(() => {
  cleanup();
  document.getElementById('modal-root')?.remove();
});

const renderModal = (data: any) => render(
  <UserSessionsModal
    isOpen
    user={{ name: 'alice' }}
    data={data}
    loading={false}
    error={null}
    onClose={() => {}}
    onRefresh={() => {}}
    onDisconnect={() => {}}
  />,
);

describe('UserSessionsModal diagnostics states', () => {
  it('labels an unavailable registry instead of presenting it as empty', () => {
    renderModal({
      nodes: [],
      global_registry: [],
      global_registry_error: 'The panel does not currently collect global registry data.',
    });

    expect(screen.getByText('Registry: Unavailable')).toBeTruthy();
    expect(screen.getByText('The panel does not currently collect global registry data.')).toBeTruthy();
    expect(screen.queryByText('No registry entries.')).toBeNull();
  });

  it('shows zero entries when registry data is available and empty', () => {
    renderModal({ nodes: [], global_registry: [] });

    expect(screen.getByText('Registry: 0')).toBeTruthy();
    expect(screen.getByText('No registry entries.')).toBeTruthy();
    expect(screen.queryByText('The panel does not currently collect global registry data.')).toBeNull();
  });

  it('marks partial node results and avoids showing unknown counts as zero', () => {
    renderModal({
      active_connections: 2,
      max_logins: 3,
      partial: true,
      unavailable_nodes: 1,
      total_nodes: 2,
      global_registry: [],
      global_registry_error: 'not collected',
      nodes: [
        { node: 'nodeA', reachable: true, live_count: 2, auth_events: 1, live_sessions: [{ common_name: 'alice' }] },
        { node: 'nodeB', reachable: false },
      ],
    });

    expect(screen.getByText('1 of 2 nodes could not provide diagnostics; counts include reachable nodes only.')).toBeTruthy();
    const nodeTable = screen.getAllByRole('table')[0];
    const unavailableRow = within(nodeTable).getByRole('row', { name: /nodeB/ });
    expect(within(unavailableRow).getByText('Unavailable')).toBeTruthy();
    expect(within(unavailableRow).getAllByText('—')).toHaveLength(2);
  });
});
