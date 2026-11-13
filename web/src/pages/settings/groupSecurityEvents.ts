// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

export interface SecurityEvent {
  action?: string;
  reason?: string;
  time_local?: string;
  ts?: number;
  user_known?: boolean;
  user?: string;
  cn?: string;
  peer?: string;
  node?: string;
  severity?: string;
  ongoing?: boolean;
}

export type GroupedSecurityEvent = SecurityEvent & { count?: number };

export const groupSecurityEvents = (list: SecurityEvent[]): GroupedSecurityEvent[] => {
  const groups = new Map<string, GroupedSecurityEvent>();
  for (const event of list) {
    const key = [event.action || '', event.user || event.cn || '', event.node || ''].join('|');
    const previous = groups.get(key);
    if (!previous) {
      groups.set(key, { ...event, count: 1 });
      continue;
    }
    previous.count = (previous.count || 1) + 1;
    if ((event.ts || 0) > (previous.ts || 0)) {
      previous.ts = event.ts;
      previous.time_local = event.time_local;
      previous.reason = event.reason;
      previous.ongoing = event.ongoing;
    } else {
      previous.ongoing = Boolean(previous.ongoing || event.ongoing);
    }
  }
  return [...groups.values()].sort((a, b) => (b.ts || 0) - (a.ts || 0));
};
