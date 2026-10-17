// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT


import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiAlertOctagon, FiAlertTriangle, FiCheckCircle, FiChevronDown, FiInfo } from 'react-icons/fi';
import { fmtDateTime } from '../../utils/time';

type AlertItem = {
  id: string;
  title: string;
  level?: string;
  link?: string;
  detail?: string;
};

type GroupKey = 'error' | 'warning' | 'info';

const GROUPS: Array<{ key: GroupKey; labelKey: string; fallback: string }> = [
  { key: 'error', labelKey: 'alertErrors', fallback: 'Errors' },
  { key: 'warning', labelKey: 'alertWarnings', fallback: 'Warnings' },
  { key: 'info', labelKey: 'alertInfo', fallback: 'Info' },
];

const groupOf = (level?: string): GroupKey => {
  const l = (level || 'warning').toLowerCase();
  if (l === 'danger' || l === 'error') return 'error';
  if (l === 'info') return 'info';
  return 'warning';
};

const SNOOZE_MS = 60 * 60 * 1000;

export default function AlertStrip({ items, onClear }: { items?: AlertItem[] | null; onClear?: (() => void) | null }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<GroupKey>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [snoozed, setSnoozed] = useState<Set<string>>(new Set());
  const [seen, setSeen] = useState<Record<string, number>>({});

  useEffect(() => {
    setSeen((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const it of items || []) {
        if (next[it.id] == null) {
          next[it.id] = Date.now();
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [items]);

  const all = items || [];
  const visible = all.filter((it) => !dismissed.has(it.id) && !snoozed.has(it.id));

  if (visible.length === 0) {
    return (
      <div className="ds-alerts ds-alerts--clear" role="status" aria-live="polite">
        <span className="ds-alerts-icon" aria-hidden="true"><FiCheckCircle /></span>
        <span className="ds-alerts-text">
          {t('allSystemsClear', 'All systems clear')}
        </span>
      </div>
    );
  }

  const grouped: Record<GroupKey, AlertItem[]> = { error: [], warning: [], info: [] };
  for (const it of visible) grouped[groupOf(it.level)].push(it);

  const toggle = (key: GroupKey) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const dismiss = (id: string) => {
    setDismissed((prev) => new Set(prev).add(id));
  };

  const snooze = (id: string) => {
    setSnoozed((prev) => new Set(prev).add(id));
    window.setTimeout(() => {
      setSnoozed((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, SNOOZE_MS);
  };

  const dismissAll = () => {
    setDismissed(new Set(visible.map((it) => it.id)));
    if (onClear) onClear();
  };

  const icons: Record<GroupKey, typeof FiInfo> = {
    error: FiAlertOctagon,
    warning: FiAlertTriangle,
    info: FiInfo,
  };

  return (
    <div
      className="ds-alerts ds-alerts--has-items"
      role="status"
      aria-live="polite"
      aria-label={`${t('attentionRequired', 'Attention required')}: ${visible.map((n) => n.title).join('. ')}`}
    >
      <div className="ds-alerts-groups">
        {GROUPS.map(({ key, labelKey, fallback }) => {
          const list = grouped[key];
          if (list.length === 0) return null;
          const isOpen = expanded.has(key);
          const Icon = icons[key];
          const first = list[0];
          return (
            <section key={key} className={`ds-alert-group ds-alert-group--${key}`}>
              <div className="ds-alert-group-head">
                <button
                  type="button"
                  className="ds-alert-group-toggle"
                  aria-expanded={isOpen}
                  aria-label={isOpen ? t('collapseAlerts', 'Collapse') : t('expandAlerts', 'Expand')}
                  onClick={() => toggle(key)}
                >
                  <span className={`ds-alert-badge ds-alert-badge--${key}`}>{list.length}</span>
                  <Icon className="ds-alert-group-icon" aria-hidden="true" />
                  <span className="ds-alert-group-label">{t(labelKey, fallback)}</span>
                  <FiChevronDown className={`ds-alert-chevron${isOpen ? ' is-open' : ''}`} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  className="ds-alert-group-msg"
                  onClick={() => first.link && navigate(first.link)}
                  title={first.detail || first.title}
                >
                  {first.title}
                </button>
              </div>
              {isOpen && (
                <ul className="ds-alert-group-body">
                  {list.map((n) => (
                    <li key={n.id} className="ds-alert-row">
                      <span className="ds-alert-row-time">
                        {seen[n.id] ? fmtDateTime(new Date(seen[n.id]).toISOString()) : '—'}
                      </span>
                      <button
                        type="button"
                        className="ds-alert-row-title"
                        onClick={() => n.link && navigate(n.link)}
                        title={n.detail || n.title}
                      >
                        {n.title}
                      </button>
                      <span className="ds-alert-row-actions">
                        <button type="button" className="ds-alert-action" onClick={() => dismiss(n.id)}>
                          {t('dismiss', 'Dismiss')}
                        </button>
                        <button type="button" className="ds-alert-action" onClick={() => snooze(n.id)}>
                          {t('snooze1h', 'Snooze 1h')}
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      {onClear && (
        <button type="button" className="ds-alerts-more" onClick={dismissAll}>
          {t('dismiss', 'Dismiss')}
        </button>
      )}
    </div>
  );
}
