# UI/UX Audit Findings Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate the UI/UX audit findings by expanding mobile action tap targets to meet WCAG 2.2 AA (44x44px), providing clear programmatic and visual focus indicators for settings tab sections, and refining audit runner console error diagnostics.

**Architecture:** Enhance mobile hit areas for `.icon-btn` controls in `styles.css` using touch-target padding/pseudo-elements; update `Settings.tsx` and `Settings.css` to add programmatic focus with visible focus rings on section navigation; update audit verification scripts to cleanly separate expected HTTP probes from unexpected runtime JavaScript exceptions.

**Tech Stack:** React 19, TypeScript, global CSS (logical properties, design tokens), Playwright.

**Spec:** UI/UX audit findings from browser testing report (`/tmp/antigravity/audit-report.json`).

## Global Constraints
- Only `tokens.css` may declare `:root` or `html[data-theme]` (enforced by `scripts/check-tokens.mjs`).
- Base CSS must use logical properties (`inset-inline`, `margin-inline`, `text-align: start`) and avoid physical left/right (enforced by `scripts/check-rtl.mjs`).
- All 4 i18n JSON files (`en`, `fa`, `ru`, `cn`) must keep identical key sets (enforced by `scripts/check-i18n.mjs`).
- Never introduce axios, external UI libraries, or extra dependencies.
- No subagents per user instructions; native inline execution.

## Review Focus
- Ensure touch target expansion does not shift or distort header flex layout on desktop (1440px) or mobile (375px).
- Verify programmatic focus on settings section change does not cause unwanted vertical scrolling jumps on first page load.
- Ensure all CI verification scripts pass (`npm run verify`).
- Verify Playwright UI audit passes cleanly with 0 unexpected console errors.

---

### Task 1: Expand Mobile Touch Targets for Header Action Controls (WCAG 2.2 AA Target Size)

**Files:**
- Modify: `web/src/styles.css`
- Test: `web/src/pages/DashboardLayout.test.tsx` (or verify via `npm run verify` and browser audit)

**Interfaces:**
- Consumes: `.ops-userbar .icon-btn` and global `.icon-btn` styles
- Produces: 44x44px effective touch target size on coarse pointer / mobile screens without affecting visual icon proportions

- [ ] **Step 1: Check existing hit area styling for `.ops-userbar .icon-btn`**

Verify current dimensions (38x38px in `styles.css`, 32x32px in `index.css`).

- [ ] **Step 2: Add touch target expansion rule for coarse pointer and mobile viewports**

In `web/src/styles.css`, add:
```css
@media (max-width: 767.98px), (pointer: coarse) {
  .ops-userbar .icon-btn {
    min-width: 44px;
    min-height: 44px;
    position: relative;
  }
}
```

- [ ] **Step 3: Run RTL and token guards**

Run: `npm run check:rtl && npm run check:tokens` in `web/`
Expected: PASS

- [ ] **Step 4: Verify layout in mobile viewport via test or audit runner**

Confirm no overflow or clipping on 375px viewport.

---

### Task 2: Settings Section Focus Indicator & Hash Jump Navigation

**Files:**
- Modify: `web/src/pages/Settings.tsx`
- Modify: `web/src/pages/Settings.css`

**Interfaces:**
- Consumes: `active.id` state in `Settings.tsx`, `.sp-section` in `Settings.css`
- Produces: Programmatic focus and highlighted active section when tab changes or deep link is navigated

- [ ] **Step 1: Update `.sp-section:focus` styling in `Settings.css`**

Add visible outline and focus styling on `:focus` (not only `:focus-visible`) so programmatic focus shows the jump-nav indicator:
```css
.sp-section:focus,
.sp-section:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 6px;
  border-radius: var(--radius-sm);
}
```

- [ ] **Step 2: Add programmatic focus on section activation in `Settings.tsx`**

When navigating to or switching sections via tab change, programmatically focus the active section container (`tabIndex={-1}`) with `preventScroll: true` to support screen readers and keyboard jump navigation:
```tsx
const sectionRef = useRef<HTMLElement>(null);
const prevActiveId = useRef(active.id);

useEffect(() => {
  if (prevActiveId.current !== active.id) {
    prevActiveId.current = active.id;
    sectionRef.current?.focus({ preventScroll: true });
  }
}, [active.id]);
```

- [ ] **Step 3: Run frontend type checks and test suite**

Run: `cd web && npm run check:types && npm test`
Expected: PASS

---

### Task 3: Refine Audit Runner Diagnostics and Re-run Full Ephemeral Verification

**Files:**
- Modify: `/tmp/antigravity/audit-runner.mjs`

**Interfaces:**
- Consumes: Playwright browser console event listener
- Produces: Clean diagnostic separation of expected HTTP 401/404 probe results vs actual unhandled client-side runtime errors

- [ ] **Step 1: Update console error filter in `/tmp/antigravity/audit-runner.mjs`**

Filter out known expected network probe responses (e.g. `401` on invalid login test, `404` on decoy root `/` test) while capturing genuine JavaScript crashes:
```javascript
const isExpectedProbeError = text.includes('401') || text.includes('404');
```

- [ ] **Step 2: Run the ephemeral UI audit suite against the live panel**

Run: `DATA_DIR=/tmp/antigravity/ovm-e2e PORT=2095 ./ovmanager & SERVER_PID=$!; sleep 1.5; node /tmp/antigravity/audit-runner.mjs; kill $SERVER_PID; wait $SERVER_PID 2>/dev/null || true`
Expected: 100% PASS across all feature and UX tests with 0 unexpected findings and zero lingering processes.

- [ ] **Step 3: Run full verification gate**

Run: `make lint && go test ./... && cd web && npm run verify`
Expected: All clean.
