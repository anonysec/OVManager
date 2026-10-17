# OVManager UI Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align OVManager frontend to a pro-max design system that matches its real identity, then polish the 3 highest-impact pages.

**Architecture:** Fix the Master-first: the generated MASTER (blue/green, Outfit) contradicts the shipped theme (orange/dark-console, Manrope). Rewrite MASTER from `tokens.css` as truth, then do per-page overrides + implementation on ServerStats, UserManagement, NodeManagement. Sequential lanes; each lane touches only its listed files.

**Tech Stack:** React 19, Vite 8, per-component CSS, react-i18next (en/fa/ru/cn + RTL), Vitest, eslint.

**Spec:** Senior-dev decisions (no open questions): (1) shipped orange/dark identity wins over generated MASTER; (2) scope = 3 pages, no global re-theme; (3) `styles.css` `.sp-*` block stays (live gap-fill, proven by prior lane); (4) no new deps.

## Global Constraints

- Touch only files listed in the task. No others.
- No new npm/pip dependencies.
- i18n: user-visible copy changes need en key + t() — sibling langs only if same key structure, else en + note.
- RTL: no physical left/right in new CSS (logical props only).
- Commit per task with `feat(ui): <task slug>` message (repo dirty already — commit only task files via explicit `git add <paths>`).

## Review Focus

- Status colors lose meaning if semantic mapping drifts (ok/warn/danger must stay distinct in dark + light).
- Dense tables overflow at 375px — every table change expects a narrow-viewport overflow check.
- Touch targets on icon buttons regress below 44px when density increases.
- Loading/empty states added without role="status" are silent to screen readers.
- fa translations fall back to English when a new key lacks fa entry.

---
### Task 1: Rewrite MASTER from shipped tokens

**Files:**
- Modify: `design-system/ovmanager/MASTER.md`
- Read: `frontend/src/tokens.css` (:root block), `frontend/src/styles.css` (1 skim for surfaces)

**Interfaces:**
- Consumes: nothing.
- Produces: MASTER describing actual theme (orange `#ff6a1a` accent, dark surfaces, Manrope + Space Grotesk) + density/status/RTL rules later tasks obey.

- [ ] **Step 1: Read tokens.css :root + skim styles.css surfaces**
- [ ] **Step 2: Rewrite MASTER.md verdict + palette + typography + spacing/status rules to match shipped tokens, keep page-override protocol section unchanged**
- [ ] **Step 3: Verify no blue/green/Outfit claims remain**

Run: `grep -in "2563EB\|059669\|Outfit\|Work Sans" design-system/ovmanager/MASTER.md`
Expected: no output

- [ ] **Step 4: Commit**

```bash
git add design-system/ovmanager/MASTER.md
git commit -m "feat(ui): master-from-shipped-tokens"
```

---
### Task 2: ServerStats pro-max pass

**Files:**
- Modify: `frontend/src/pages/ServerStats.tsx`, `frontend/src/pages/Dashboard.css` (or its actual CSS — confirm name first)
- Read: `design-system/ovmanager/MASTER.md`, `design-system/ovmanager/pages/dashboard.md` (create via --page override first if missing)

**Interfaces:**
- Consumes: MASTER tokens from Task 1.
- Produces: KPI/chart composition with token-driven accents, status semantics, skeleton/empty coverage.

- [ ] **Step 1: Create page override**

Run: `python3 /root/.config/opencode/skills/ui-ux-pro-max/scripts/search.py "ops metrics dashboard kpi chart" --design-system --persist -p "OVManager" --page "serverstats" --output-dir "/root/workspace/OVManager" --density 8 --motion 3 -f markdown`
Expected: pages/serverstats.md created, palette section matches MASTER (override only layout/density)

- [ ] **Step 2: Implement override in ServerStats (token vars only, no hex; KPI hierarchy; chart legends labeled; loading skeleton + empty states with role="status")**
- [ ] **Step 3: Lint touched files**

Run: `npx eslint src/pages/ServerStats.tsx` (from frontend/)
Expected: clean

- [ ] **Step 4: Run related tests**

Run: `npm test -- ServerStats` (from frontend/)
Expected: PASS (or "no tests" — then note it)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ServerStats.tsx frontend/src/pages/Dashboard.css design-system/ovmanager/pages/serverstats.md
git commit -m "feat(ui): serverstats promax pass"
```

---
### Task 3: UserManagement pro-max pass

**Files:**
- Modify: `frontend/src/pages/UserManagement.tsx`, `frontend/src/pages/UserManagement.css`
- Read: `design-system/ovmanager/MASTER.md`

**Interfaces:**
- Consumes: MASTER + page-override pattern from Task 2.
- Produces: table density/overflow fix, status badge semantics, modal focus already done — verify untouched.

- [ ] **Step 1: Create page override (`--page "usermanagement"`, same command shape as Task 2 with query "admin users table management")**
- [ ] **Step 2: Implement (cell density via tokens, overflow ellipsis + title, status colors from MASTER, 375px scroll container, touch targets ≥44px)**
- [ ] **Step 3: Lint**

Run: `npx eslint src/pages/UserManagement.tsx` (from frontend/)
Expected: clean

- [ ] **Step 4: Run related tests**

Run: `npm test -- UserManagement` (from frontend/)
Expected: PASS (or note no tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/UserManagement.tsx frontend/src/pages/UserManagement.css design-system/ovmanager/pages/usermanagement.md
git commit -m "feat(ui): usermanagement promax pass"
```

---
### Task 4: NodeManagement pro-max pass

**Files:**
- Modify: `frontend/src/pages/NodeManagement.tsx`, `frontend/src/pages/NodeManagement.css`
- Read: `design-system/ovmanager/MASTER.md`

**Interfaces:**
- Consumes: MASTER + pattern from Tasks 2–3.
- Produces: health/status semantics (ok/warn/danger mapping), NodeDrawer coordination (no focus regression — focus code stays), responsive drawer width.

- [ ] **Step 1: Create page override (`--page "nodemanagement"`, query "server node fleet status management")**
- [ ] **Step 2: Implement (status color mapping per MASTER, drawer responsive widths, no change to NodeDrawer focus logic)**
- [ ] **Step 3: Lint**

Run: `npx eslint src/pages/NodeManagement.tsx` (from frontend/)
Expected: clean

- [ ] **Step 4: Run related tests**

Run: `npm test -- NodeManagement` (from frontend/)
Expected: PASS (or note no tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/NodeManagement.tsx frontend/src/pages/NodeManagement.css design-system/ovmanager/pages/nodemanagement.md
git commit -m "feat(ui): nodemanagement promax pass"
```

---
### Task 5: Full verify + graph refresh

**Files:** none (verification only)

- [ ] **Step 1: Frontend verify**

Run: `npm run verify` (from frontend/)
Expected: PASS

- [ ] **Step 2: Backend lint untouched check**

Run: `git status --short -- backend/ | head -5`
Expected: no output (no backend drift)

- [ ] **Step 3: Refresh graph**

Run: `graphify update .` (from repo root)
Expected: node/edge counts printed
