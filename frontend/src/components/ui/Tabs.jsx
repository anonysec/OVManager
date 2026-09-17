// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useRef } from 'react';
import './Tabs.css';

/**
 * Tabs — accessible tab strip (no panel rendering: the caller owns the
 * tabpanel and points aria-labelledby at `tab-<id>`).
 *
 * Keyboard model follows the WAI-ARIA tabs pattern: one tab is tabbable
 * (roving tabindex), arrows move + activate, Home/End jump to the ends.
 * Automatic activation is deliberate — every panel here renders local data.
 */
const Tabs = ({ tabs = [], value, onChange, ariaLabel, className = '' }) => {
  const listRef = useRef(null);
  const found = tabs.findIndex((tab) => tab.id === value);
  const activeIndex = found === -1 ? 0 : found;

  const focusTab = (index) => {
    if (!tabs.length) return;
    const next = (index + tabs.length) % tabs.length;
    const node = listRef.current?.querySelectorAll('[role="tab"]')[next];
    onChange?.(tabs[next].id);
    node?.focus();
  };

  const onKeyDown = (e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      focusTab(activeIndex + 1);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      focusTab(activeIndex - 1);
    } else if (e.key === 'Home') {
      e.preventDefault();
      focusTab(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      focusTab(tabs.length - 1);
    }
  };

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={ariaLabel}
      className={['ui-tabs', className].filter(Boolean).join(' ')}
      onKeyDown={onKeyDown}
    >
      {tabs.map((tab) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            disabled={tab.disabled}
            className={['ui-tab', selected ? 'ui-tab--active' : ''].filter(Boolean).join(' ')}
            onClick={() => onChange?.(tab.id)}
          >
            {tab.icon && <span className="ui-tab-icon" aria-hidden="true">{tab.icon}</span>}
            <span className="ui-tab-label">{tab.label}</span>
            {tab.count != null && <span className="ui-tab-count">{tab.count}</span>}
          </button>
        );
      })}
    </div>
  );
};

export default Tabs;
