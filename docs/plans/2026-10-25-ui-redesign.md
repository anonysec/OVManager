# OVManager UI Redesign Plan
**Authored:** 2026-10-25  
**Status:** Ready for implementation — implement all phases, then Claude reviews the whole result once at the end.  
**Who implements:** Engineer. Claude does not touch code. Claude reviews once when all phases are done.  
**Constraint:** No mid-phase review gates. Every task ships its own self-check so the implementer knows it is correct without external review.

---

## Corrections from initial analysis — read this first

Two assumptions in the earlier critique were wrong. The actual codebase differs:

**1. Font system is already self-hosted.**  
`web/public/fonts/fonts.css` declares all `@font-face` blocks for Manrope (weights 400–800, 6 subsets each) and Space Grotesk. Both fonts load from `web/public/fonts/*.woff2`. There is no CDN dependency. The Phase 4 typography task (replace Manrope with Inter) is therefore **cancelled** — it would require downloading, subsetting, and declaring ~30 new `@font-face` blocks for equivalent coverage, all to replace a font that is already correctly self-hosted and performs fine. The tabular-number sub-task (Task 4.2) is **kept** as a standalone micro-task appended to Phase 3 — it is 4 lines of CSS and has nothing to do with font replacement.

**2. Accent color is user-selectable at runtime.**  
`AppearanceSection.tsx` exposes an `ACCENTS` picker (Orange, Emerald, Indigo, Rose, Cyan, Amber). Choosing one calls `document.documentElement.style.setProperty('--accent-color', hex)`. The whole Phase 2 premise — "orange means everything, we need a separate `--brand` token for interactive elements" — **collides directly with this feature**. If primary buttons and focus rings use `--brand` (blue), the user's chosen accent color becomes purely decorative and the picker setting is misleading. The accent picker is a product decision that was made deliberately. **Phase 2 is redesigned** around this reality: the correct fix is not to split accent from brand, but to stop using accent for *data-viz fill* (the KPI meter bar at normal utilization) and *status indicators* (which must never share color with interactive elements). The picker stays exactly as-is.

---

## Ground truth before any task starts

Run these commands and keep the output for comparison after each phase:

```bash
# Baseline counts — compare after each phase
wc -l web/src/styles.css                          # should be 3018
grep -c "!important" web/src/styles.css           # should be 71
grep -rn "\"btn " web/src --include="*.tsx" | wc -l   # should be ~30
npm run verify                                    # must pass clean as baseline
```

Store the `npm run verify` baseline output. After every phase the output must be identical (same test count, same pass count, no new warnings).

---

## Immovable house rules

Every task must respect these. They are enforced by CI scripts that the implementer runs as the self-check.

1. **`tokens.css` only** — no `:root` or `html[data-theme]` in any other file. Violation caught by `npm run check:tokens`.
2. **Logical CSS** — never `left`, `right`, `margin-left`, `padding-left`, `text-align: left|right` outside `html[dir="rtl"]` or a `/* rtl-ok: reason */` line. Caught by `npm run check:rtl`.
3. **Token-only colors** — no hardcoded hex in component CSS. Any `var(--x)` must resolve to a declared token. Caught by `npm run check:tokens` (runs after build).
4. **4-locale parity** — any new i18n key in `en.json` must also exist in `fa.json`, `ru.json`, `cn.json`. Caught by `npm run check:i18n`.
5. **No new dependencies** — no npm packages, no CDN links, no new `<link>` in `index.html`.
6. **Copyright header** — every new `.css` or `.tsx` file: `/* Copyright (c) 2026 anonysec` + `/* SPDX-License-Identifier: MIT */` for CSS, `// Copyright (c) 2026 anonysec` + `// SPDX-License-Identifier: MIT` for TSX.
7. **No Go files** — this plan is frontend-only.
8. **Self-check after every task** — `cd web && npm run verify` must pass before starting the next task. A failing verify mid-phase means the current task broke something; fix it before continuing.

---

## Phase 1 — CSS Architecture: Decompose `styles.css`

**What and why:** `styles.css` is 3 018 lines holding rules for the sidebar, topbar, modals, node drawer, toasts, skeleton, route progress, command palette, and more — all in one file with no structural separation. 71 `!important` overrides exist because cascading collisions built up over time. This phase moves every block to a co-located CSS file that the owning component imports directly. **Zero visual change. Zero token changes.** It is purely structural — the browser sees identical CSS, just loaded from different files in the same cascade order (component CSS loads when the component renders, and all components are already mounted by the time any rule is needed).

**Risk:** The cascade order of `tokens.css → index.css → styles.css → page CSS` currently determines which rule wins when selectors tie. After this phase, the order becomes `tokens.css → index.css → [component CSS files in mount order] → page CSS`. Because React mounts components in a predictable order (DashboardLayout → Sidebar → TopBar → page), and because the rules being moved are component-scoped (they only apply inside `.node-drawer` or `.ops-topbar-minimal`), cascade order conflicts are unlikely. Any conflict that does appear will manifest as a visual regression — the self-check screenshots will catch it.

**Self-check for the whole phase:**  
After all tasks in Phase 1 are done:
```bash
wc -l web/src/styles.css          # target: ≤ 150 lines
grep -c "!important" web/src/styles.css   # target: ≤ 20 (down from 71)
cd web && npm run verify           # must pass clean
```
Then visually check these 9 routes in both dark and light theme: `/login`, `/`, `/server`, `/users`, `/nodes`, `/audit`, `/logs`, `/settings`, `/setup`. Any visual difference from baseline is a bug in this phase.

---

### Task 1.1 — Create `TopBar.css`; move topbar, breadcrumb, userbar, language picker

**Create:** `web/src/components/TopBar.css`

**Add import to:** `web/src/pages/DashboardLayout.tsx`  
Place `import '../components/TopBar.css';` after the existing imports, before any JSX.

**Move these blocks from `styles.css` into `TopBar.css`** (cut from `styles.css`, paste verbatim into new file — no edits to the CSS rules themselves):

| What | Approx lines in `styles.css` |
|------|------|
| `.ops-userbar` initial declaration (first occurrence near line 22) | ~3 lines |
| `.ops-userbar button:not(...)` rules (first occurrence) | ~3 lines |
| User corner section: `.lang-picker-wrap`, `.lang-picker-btn`, `.lang-dropdown`, `.lang-option`, `.lang-check` | ~35 lines, around line 658–700 |
| `.ops-topbar-minimal` and all its children: `.topbar-search-trigger`, `kbd` inside it, `.ops-breadcrumb ol`, `.ops-breadcrumb-separator`, `.ops-current-page`, `.ops-userbar .icon-btn`, `.ops-userbar .icon-btn-badge`, `.ops-userbar .icon-btn:hover`, `.ops-userbar .icon-btn.active`, `.ops-userbar .icon-btn.has-alerts` | ~90 lines, around line 941–1060 |
| All `@media` blocks that touch only topbar/userbar selectors (the ones inside the 900px and 767.98px breakpoints that mention `.ops-topbar-minimal`, `.topbar-search-trigger`, `.ops-userbar`) | ~90 lines, around line 1273–1370 |
| `html[data-theme="light"] .ops-topbar-minimal` and light-mode topbar overrides | ~20 lines, around line 1372–1388 |
| `html[dir="rtl"] .ops-userbar` | ~3 lines, around line 555 |
| Focus-visible rules for userbar buttons (`.ops-userbar button:focus-visible`) | ~5 lines, around line 901 |

**How to find each block precisely:** Search `styles.css` for the selector text. The blocks are separated by blank lines and section comments. Copy the entire block including its comment header.

**Self-check:**
```bash
grep -n "ops-topbar\|ops-userbar\|lang-picker\|lang-dropdown\|topbar-search" web/src/styles.css
# Should return only the lines that were deliberately left (if any)
# All the moved selectors must now be absent from styles.css

grep -n "ops-topbar\|ops-userbar\|lang-picker\|lang-dropdown\|topbar-search" web/src/components/TopBar.css
# Should return all the moved selectors

cd web && npm run check:rtl      # must pass
```

---

### Task 1.2 — Create `Sidebar.css`; move sidebar, profile, mobile drawer

**Create:** `web/src/components/Sidebar.css`

**Add import to:** `web/src/components/Sidebar.tsx`  
Add `import './Sidebar.css';` near the top, after the existing imports.

**Move from `styles.css`:**

| What | Approx lines |
|------|------|
| `.ops-sidebar` and children: `.sidebar-brand`, `.sidebar-nav`, `.sidebar-nav-list`, `.sidebar-nav-link`, `.sidebar-nav-link.active`, `.sidebar-nav-link.active::after`, collapse transition rules | ~50 lines, around line 1213–1260 |
| Sidebar profile block: `.sidebar-profile`, `.sidebar-user`, `.sidebar-user-name`, `.sidebar-user-role`, `.sidebar-logout`, and their hover/focus states | ~80 lines, around line 1735–1818 |
| Sidebar collapse button: `.sidebar-collapse-btn` and its states | ~20 lines |
| Phone off-canvas sidebar: `.sidebar-drawer` (the mobile variant), `.sidebar-backdrop`, mobile breakpoint rules for the sidebar | ~90 lines, around line 1905–1994 |
| `html[dir="rtl"]` sidebar rules | any RTL sidebar rules in the file |

**Self-check:**
```bash
grep -n "\.sidebar-\|\.ops-sidebar\|sidebar-drawer\|sidebar-backdrop" web/src/styles.css
# Only lines not belonging to Sidebar should remain (should be very few or zero)

cd web && npm run check:rtl
```

---

### Task 1.3 — Create `RouteProgress.css`, `ShortcutsHelp.css`, `CommandPalette.css`

Three small standalone files. Each is created, populated, and imported from its component.

**`web/src/components/RouteProgress.css`**  
Import from: `web/src/components/RouteProgress.tsx` → `import './RouteProgress.css';`  
Move from `styles.css`: the `.route-progress` block and its `@keyframes route-progress-*` animations (~35 lines, around line 1995–2029).

**`web/src/components/ShortcutsHelp.css`**  
Import from: `web/src/components/ShortcutsHelp.tsx` → `import './ShortcutsHelp.css';`  
Move from `styles.css`: `.shortcuts-sheet`, `.shortcuts-key`, `.shortcuts-row`, `.shortcuts-group`, `.shortcuts-title`, `.shortcuts-close`, and any associated states (~48 lines, around line 2145–2191).

**`web/src/components/CommandPalette.css`**  
Import from: `web/src/components/CommandPalette.tsx` → `import './CommandPalette.css';`  
Move from `styles.css`: the search bar and command palette overlay blocks — `.search-field`, `.search-input`, `.search-results`, `.search-result-item`, `.pal-*` classes, and the date-input shortcuts block (~65 lines, around line 594–660 and 603–610).

**Self-check for all three:**
```bash
grep -n "route-progress\|shortcuts-\|search-field\|search-input\|\.pal-" web/src/styles.css
# Should return zero results

cd web && npm run verify
```

---

### Task 1.4 — Create `Modal.css`; merge node drawer rules into `NodeDrawer.css`

**`web/src/components/Modal.css`** (new)  
Import from: `web/src/components/Modal.tsx` → `import './Modal.css';`  
Move from `styles.css`:
- Modal overlay and window: `.modal-overlay`, `.modal-window`, `.modal-content`, `.modal-header`, `.modal-footer`, `.modal-title`, `.modal-close`, `.modal-actions` (~48 lines, around line 280–327)
- ConfirmModal actions row: `.confirm-modal-actions` (~7 lines, around line 1629–1636)
- Light-mode modal overrides: `html[data-theme="light"] .modal-window` (~3 lines)

**`web/src/components/NodeDrawer.css`** (already exists — append to it)  
Do NOT create a new file. Open the existing `NodeDrawer.css` and append these blocks from `styles.css`:
- `.node-drawer-backdrop`, `.node-drawer`, `.node-drawer-head`, `.node-drawer-tabs`, `.node-drawer-body` (~55 lines, around line 2070–2123)
- Node drawer log viewer: `.node-log-line`, `.node-log-ts`, `.node-log-msg` (~40 lines, around line 2957–2994)

After appending: search the existing `NodeDrawer.css` for any selectors that duplicate what you just appended. If `.node-drawer` is declared twice, keep the new (more complete) version and delete the old stub.

**Self-check:**
```bash
grep -n "modal-overlay\|modal-window\|node-drawer-backdrop\|node-drawer-body\|node-log-line" web/src/styles.css
# Must return zero results

grep -n "node-drawer" web/src/components/NodeDrawer.css | wc -l
# Should be a healthy number (>5) — confirms the move landed

cd web && npm run verify
```

---

### Task 1.5 — Move primitive-component styles to `ui/` files

Each block moves from `styles.css` to a CSS file in `web/src/components/ui/`. For primitives that already have a CSS file, append to it. For those that don't, create one and add an import in the TSX.

**`ErrorState.css`** (create, import from `ErrorState.tsx`)  
Move: `.error-state`, `.error-state-icon`, `.error-state-title`, `.error-state-body`, `.error-state-retry` (~35 lines, around line 703–789 — read carefully, the EmptyState block follows immediately).

**`EmptyState.css`** (create, import from `EmptyState.tsx`)  
Move: `.empty-state`, `.empty-state-icon`, `.empty-state-title`, `.empty-state-action` (~35 lines, around line 790–834).

**`Badge.css`** (already exists — append)  
Move: `.status-badge`, `.status-badge--online`, `.status-badge--offline`, `.status-badge--warning`, `.status-badge--neutral`, and the associated `@keyframes` if any (~42 lines, around line 856–898).  
Do not duplicate: check `Badge.css` first to confirm `.status-badge` is not already defined there.

**`Skeleton.css`** (create, import from `Skeleton.tsx`)  
Move: `.skeleton-block`, `.skeleton-text`, `.panel-skeleton`, `.panel-skeleton-line`, `@keyframes skeleton-pulse` (~50 lines, around line 835–858 and 2192–2241 — there may be two separate skeleton blocks; merge them into one file).  
Move: `.section-boundary` or similar SectionBoundary styles (~30 lines, around line 2242–2273).

**Self-check:**
```bash
grep -n "error-state\|empty-state\|status-badge\|skeleton-block\|panel-skeleton\|section-boundary" web/src/styles.css
# Must return zero

cd web && npm run check:tokens   # requires npm run build first
npm run build && npm run check:tokens
```

---

### Task 1.6 — Move page-specific overrides to their page CSS files

Append each block (verbatim, no edits) to the correct page CSS file. Every destination file already exists.

| Block in `styles.css` | Approx lines | Destination |
|----------------------|------|-------------|
| User management pills, online-view, search/filter overrides | ~60 lines, around line 360–421 | `web/src/pages/UserManagement.css` |
| Modal form layout (single definition, one size, one rhythm) | ~57 lines, around line 422–478 | `web/src/pages/UserManagement.css` (these are user modals) |
| Custom checkbox styles | ~22 lines, around line 479–500 | `web/src/pages/UserManagement.css` |
| User detail popup: `.user-detail-*` | ~12 lines, around line 568–579 | Create `web/src/components/UserDetailModal.css`, import from `UserDetailModal.tsx` |
| Node picker / subscription styles: `.node-picker-*` | ~14 lines, around line 580–593 | `web/src/components/SelectNodeForDownloadModal.css` (already exists — append) |
| Dashboard quick actions: `.ds-quick-actions` | ~3 lines, around line 2052–2054 | `web/src/pages/Dashboard.css` |
| Accent picker: `.accent-picker`, `.accent-swatch` | ~15 lines, around line 2055–2069 | `web/src/pages/settings/AppearanceSection.css` (create if absent, import from `AppearanceSection.tsx`) |
| Toast dismiss button styles | ~20 lines, around line 2124–2144 | Create `web/src/context/ToastContext.css`, import from `ToastContext.tsx` |
| Usage history graph: `.usage-graph-*` | ~4 lines, around line 2953–2956 | `web/src/components/UserDetailModal.css` |
| Touch ergonomics mobile block (the large `@media (max-width: 767.98px)` block at end of file covering node rows, user rows, action buttons) | ~23 lines, around line 2995–3018 | Split: node-related lines → `NodeManagement.css`, user-related → `UserManagement.css` |
| Filter chips: `.filter-chip`, `.filter-chip--active` | ~22 lines, around line 2030–2051 | `web/src/components/ui/Badge.css` or `web/src/index.css` (these are global; put them where other chip/pill styles live — check `index.css` first) |

For `AppearanceSection.css`: the AGENTS.md for the settings sub-package notes that `.btn` selectors inside a settings stylesheet **must** be scoped under `.sp-page`. The accent picker has no `.btn` selectors so this rule doesn't apply, but note it for any future settings CSS additions.

**Self-check:**
```bash
# After all moves:
wc -l web/src/styles.css    # target: ≤ 150

# Check nothing was lost — sample a few moved selectors:
grep -n "accent-picker\|ds-quick-actions\|user-detail-\|node-picker\|toast-dismiss\|usage-graph" web/src/styles.css
# Must return zero

cd web && npm run verify
```

---

### Task 1.7 — Retire the legacy `.btn` system

**Context:** Two button systems coexist. The modern `ui-btn` system (in `Button.css`) is correct. The legacy `.btn` system (in `index.css` lines 136–202 and scattered `styles.css` lines) is used by ~30 callsites across settings sections, modals, and `ActivityFeed`. They look identical on screen because `styles.css` applies similar geometry, but their `:focus-visible` rings differ and they will diverge over time.

**Step A — Update every callsite.** Find all legacy `.btn` uses:
```bash
grep -rn "\"btn \|\"btn\"\| btn btn\| btn-sm\| btn-danger\| btn-secondary\| btn-success\| btn-primary" web/src --include="*.tsx"
```

For each result, replace with the `ui-btn` equivalent:

| Legacy class string | Replacement |
|---------------------|-------------|
| `"btn btn-sm"` | `"ui-btn ui-btn--primary ui-btn--sm"` |
| `"btn btn-sm btn-secondary"` | `"ui-btn ui-btn--secondary ui-btn--sm"` |
| `"btn btn-sm btn-danger"` | `"ui-btn ui-btn--danger ui-btn--sm"` |
| `"btn btn-sm btn-success"` | `"ui-btn ui-btn--success ui-btn--sm"` |
| `"btn btn-primary btn-sm"` | `"ui-btn ui-btn--primary ui-btn--sm"` |
| `"btn btn-secondary"` | `"ui-btn ui-btn--secondary"` |
| `"btn btn-danger"` | `"ui-btn ui-btn--danger"` |
| `"btn btn-success"` | `"ui-btn ui-btn--success"` |

Files that need updating (verified from source):

- `web/src/components/dashboard/ActivityFeed.tsx` line 29
- `web/src/pages/settings/GeneralSection.tsx` lines 170, 171, 198, 199, 223
- `web/src/pages/settings/TelegramSection.tsx` lines 122, 128
- `web/src/pages/settings/SystemSection.tsx` lines 262, 273, 303, 306, 309, 344, 348, 356
- `web/src/pages/settings/BackupSection.tsx` lines 191, 195, 313, 331
- `web/src/pages/settings/AlertsSection.tsx` lines 181, 208
- `web/src/pages/settings/DefaultsSection.tsx` line 83
- `web/src/pages/settings/MyActivitySection.tsx` line 105
- `web/src/pages/settings/AppearanceSection.tsx` line 179
- `web/src/pages/settings/DisplaySection.tsx` lines 87, 88
- `web/src/components/UserSessionsModal.tsx` lines 86, 87
- `web/src/components/SelectNodeForDownloadModal.tsx` lines 160, 161

**Step B — Update `LoadingButton.tsx`.**  
Open `web/src/components/LoadingButton.tsx`. It accepts a `className` prop from callers (which will now pass `ui-btn ui-btn--primary ui-btn--sm`). Check whether it internally prepends `btn` to the className or emits `btn` as a base class. If it does, change that internal base class to `ui-btn`. The spinner markup and loading logic must not change.

**Step C — Confirm `settingsButtonScope.test.ts` still passes.**  
This test reads every `.css` file in the settings tree and fails if any `.btn` selector does not start with `.sp-page`. After Step A and B, there should be no bare `.btn` selectors left in settings CSS — the test should pass with no changes needed. But run it explicitly:
```bash
cd web && npm test -- --run settingsButtonScope
```

**Step D — Delete the legacy `.btn` CSS.**  
Only do this AFTER Steps A–C pass.

In `web/src/index.css`, delete the entire `.btn` block (lines 136–202, including `.btn`, `.btn:hover`, `.btn:active`, `.btn:disabled`, `.btn.btn-sm`, `.btn.btn-danger`, `.btn.btn-danger:hover`, `.btn.btn-success`, `.btn.btn-success:hover`).

In `web/src/styles.css`, delete:
- Line ~32: `.btn:hover { filter: brightness(1.08); }` (the early override)
- Lines ~55–56: `.btn-danger` and `.btn-danger:hover`
- Line ~278: the `body, .ops-nav-link, ..., .btn { font-family: ... }` reference to `.btn`
- Lines ~754–799: `.btn-retry`, `.btn-secondary` standalone blocks
- Lines ~900–915: `.btn:focus-visible` focus ring block

**Self-check — the definitive check:**
```bash
grep -rn "\"btn \|\"btn\"\| btn btn\| btn-sm\| btn-danger\| btn-secondary\| btn-success\| btn-primary" web/src --include="*.tsx"
# Must return zero results

grep -rn "\.btn[^-]" web/src --include="*.css"
# Must return zero (only ui-btn prefix should remain)

cd web && npm run verify
# All 81 tests must still pass
```

---

### Task 1.8 — Clean up what remains in `styles.css`

After all moves and deletions, `styles.css` should contain only:

1. The copyright header
2. `* { box-sizing: border-box; }` and `body` base reset (background, color, font-family, margin, overflow)
3. The body background radial gradients (`radial-gradient(...)`)
4. `@keyframes fadeUp`, `@keyframes botFloat`, `@keyframes lineDraw` (used by login/setup animation)
5. `.view { animation: fadeUp ... }` (global page fade-in)
6. `.dot` and `.dot.online` (the inline status dot used in several places — check if it can move to `Badge.css`)
7. Global `html[data-theme="light"] body` override
8. The `html[dir="rtl"] body` override
9. The large `@media (max-width: 1180px)` overflow rule for body

Anything else still in the file that was not moved by Tasks 1.1–1.7 must be explicitly decided: either moved to its correct owner, or documented with a comment explaining why it is global.

**Final self-check for Phase 1:**
```bash
wc -l web/src/styles.css            # target: ≤ 150
grep -c "!important" web/src/styles.css  # target: ≤ 15 (most were in moved blocks)
cd web && npm run verify             # must pass clean, 81 tests
```

Take screenshots of all 9 routes in dark mode and light mode. Compare to baseline. Any visual difference is a regression to fix before starting Phase 2.

---

## Phase 2 — Accent Semantics: Stop Using Accent for Data Fill

**What and why — revised from original plan.**  
The user-selectable accent picker in `AppearanceSection.tsx` sets `--accent-color` on `documentElement.style` at runtime. This means the accent color is intentionally shared across interactive elements (buttons, focus rings, sidebar active state) and brand decoration (logo, login border). **That design decision stands — do not change it.**

The actual problem is narrower: `--accent-text` (the orange tone safe for text on dark backgrounds) is used as the fill color for the KPI meter bar at normal utilization (`Dashboard.css` line 218). This means the orange bar inside a healthy KPI card uses the same color as a primary button — the operator's eye cannot distinguish "data bar" from "I can click this." Status fills (dots, bars, meter fills) must use dedicated semantic status tokens, not the accent color.

Additionally, the body background gradient uses `rgba(255,122,30,.10)` — a hardcoded orange. This is a minor consistency issue: a user who picks Indigo as their accent still sees an orange glow on the body background.

**Zero button changes. Zero focus ring changes. Zero sidebar changes.** Those are correct and intentional.

**Self-check for the whole phase:**
```bash
# After all Phase 2 tasks:
grep -n "accent-text\|accent-color\|var(--accent)" web/src/pages/Dashboard.css
# Must not show the KPI meter fill line using accent tokens

cd web && npm run verify
```

---

### Task 2.1 — Fix KPI meter fill: replace accent token with neutral fill

**File:** `web/src/pages/Dashboard.css`

Find the `.ds-kpi-meter-fill` rule (around line 218):
```css
.ds-kpi-meter-fill {
  display: block;
  height: 100%;
  background: var(--accent-text);   /* ← this line is the problem */
  transition: width var(--transition-normal);
}
```

The `.ds-kpi--ok`, `.ds-kpi--warn`, `.ds-kpi--danger` modifier classes already override this for the three status states (`var(--success)`, `var(--warning)`, `var(--danger)`). The base rule only fires when *no status class is applied* — i.e., neutral/informational KPI tiles. Change the base fill to the info/neutral token:

```css
.ds-kpi-meter-fill {
  display: block;
  height: 100%;
  background: var(--info);          /* neutral data fill: cyan, not accent orange */
  transition: width var(--transition-normal);
}
```

**Why `--info` not `--accent`:** `--info` (`#19d3e9` dark / `#0891b2` light) is a status-semantic token meaning "informational, no urgency." A meter bar at neutral utilization has no urgency. `--accent` is the user's chosen interaction color — it should only appear on things they can click.

**Self-check:**
```bash
grep -n "ds-kpi-meter-fill" web/src/pages/Dashboard.css
# The base rule must show var(--info), not var(--accent-text)

# Visual: open dashboard in browser, find a KPI card with a meter bar that has no warn/danger state
# The bar should now be cyan (dark mode) or teal (light mode) instead of orange
# Cards with --warn or --danger still show amber/red — those modifiers are unchanged
```

---

### Task 2.2 — Fix body background gradient: use CSS custom property instead of hardcoded hex

**File:** `web/src/styles.css` (or after Phase 1, wherever the body background gradient lives — it stays in `styles.css` per Task 1.8)

Find the body background in `styles.css`:
```css
body {
  ...
  background-image:
    radial-gradient(1100px 600px at 12% -8%, rgba(255,122,30,.10), transparent 60%),
    radial-gradient(900px 600px at 100% 0%, rgba(23,200,235,.08), transparent 55%);
}
```

The `rgba(255,122,30,.10)` is a hardcoded orange value. Replace it with the accent soft token at low opacity. The `--accent-soft` token is already `rgba(255, 106, 26, 0.12)` in dark mode and a similar orange in light mode — slightly different hue from the hardcoded value, close enough:

```css
body {
  ...
  background-image:
    radial-gradient(1100px 600px at 12% -8%, var(--accent-soft), transparent 60%),
    radial-gradient(900px 600px at 100% 0%, rgba(23,200,235,.08), transparent 55%);
}
```

This means when a user selects Indigo as their accent, the body glow subtly shifts to indigo. When they select Emerald, it shifts to green. The background responds to the accent picker, which is coherent product behavior.

**Important note on `--accent-soft` opacity:** `--accent-soft` is already defined as `rgba(255, 106, 26, 0.12)` — it includes opacity. The `radial-gradient` transparency stop will still apply, so the effective opacity at the gradient center is 0.12 and fades to 0. This is slightly brighter than the original 0.10. If it reads as too strong visually, add an additional wrapper: `color-mix(in srgb, var(--accent-soft) 85%, transparent)` — but test visually first.

**Self-check:**
```bash
grep -n "rgba(255,122,30\|rgba(255, 122" web/src/styles.css
# Must return zero — no hardcoded orange hex left

cd web && npm run verify
# The check:tokens script does NOT catch hardcoded hex in non-component files (only in built CSS)
# So this is a manual grep check only
```

---

### Task 2.3 — Tabular numbers on metric cells

This was originally Phase 4 Task 4.2. It belongs here because it touches `Dashboard.css` which Phase 2 already opens.

**File:** `web/src/pages/Dashboard.css`

In the `.ds-kpi-value` rule (around line 153), add one line:

```css
.ds-kpi-value {
  /* existing rules unchanged */
  font-variant-numeric: tabular-nums;  /* already present! check first */
  font-feature-settings: "tnum" 1;     /* ADD: explicit feature tag for full support */
}
```

Check first: `font-variant-numeric: tabular-nums` may already be declared on this element (the source showed it at line 160). If so, just add `font-feature-settings: "tnum" 1` as the only new line. Do not duplicate `font-variant-numeric`.

**File:** `web/src/pages/NodeManagement.css`

Find `.nm-users-value` (the live session count number). Add:
```css
.nm-users-value {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}
```

**File:** `web/src/components/ui/StatCard.css`

Open `StatCard.css`. Find the class used for the numeric value in `StatCard.tsx` (inspect the TSX to find the exact class name — it will be something like `.stat-card-value` or `.ui-stat-value`). Add `font-feature-settings: "tnum" 1` to that rule.

**Self-check:**
```bash
grep -n "font-feature-settings\|tabular-nums" web/src/pages/Dashboard.css web/src/pages/NodeManagement.css web/src/components/ui/StatCard.css
# Each file must show the declaration on the numeric value element

cd web && npm run verify
```

---

## Phase 3 — Node Fleet Readability

**What and why:** The node list page is the primary operational surface — the place an operator goes first when something is wrong. Currently, every node card looks identical at a glance: same border, same background, same visual weight regardless of health state. A health status exists in the code (`health = 'online' | 'warning' | 'offline'` at `NodeManagement.tsx` line 335) but only drives a `StatusBadge` label. The operator must read text to know which nodes need attention.

Two changes: (1) a colored inline-start border on each card encodes health at a glance, (2) a conditional meta row shows the specific problem (TLS warning, unreachable state) for degraded nodes without requiring a drawer click.

Additionally, the node drawer (623 lines) has no fixed footer — on a long content tab the close button scrolls off-screen. A minimal footer fix corrects this.

**Self-check for the whole phase:**
```bash
cd web && npm run verify

# Visual: open /nodes in browser
# With one offline node: red border on left side of card, meta row with red chip visible
# With one self-signed TLS node: amber border, meta row with "Self-signed" chip visible
# With all online + verified TLS nodes: green borders, NO meta rows visible (quiet by default)
# Node drawer: close button always visible at top; footer with Edit + Download always visible at bottom regardless of scroll position
```

---

### Task 3.1 — Health border on node cards

**File:** `web/src/pages/NodeManagement.css`

Find the existing `.nm-node` rule:
```css
.nm-node {
  overflow: hidden;
}
```

Change to:
```css
.nm-node {
  overflow: hidden;
  border-inline-start: 3px solid transparent;
  transition: border-color var(--transition-fast);
}

.nm-node--online  { border-inline-start-color: var(--success); }
.nm-node--warn    { border-inline-start-color: var(--warning); }
.nm-node--offline { border-inline-start-color: var(--danger); }
```

**File:** `web/src/pages/NodeManagement.tsx`

Find line 338 (the Card render inside the node list):
```tsx
<Card as="article" key={node.id} className="nm-node" padded={false}>
```

Change to:
```tsx
<Card as="article" key={node.id} className={`nm-node nm-node--${health}`} padded={false}>
```

`health` is already defined at line 335 as `'online' | 'warning' | 'offline'`. No new logic, no new API call, no new state.

**Self-check:**
```bash
grep -n "nm-node--\|border-inline-start" web/src/pages/NodeManagement.css
# Must show the three modifier rules and the base border declaration

grep -n "nm-node--\${health}" web/src/pages/NodeManagement.tsx
# Must show the updated className

cd web && npm run check:rtl    # border-inline-start is a logical property — must pass
cd web && npm run verify
```

---

### Task 3.2 — Node meta sub-row for degraded state visibility

**File:** `web/src/pages/NodeManagement.tsx`

Add `FiShield` to the existing import from `react-icons/fi` at line 4:
```tsx
import {
  FiCheckCircle, FiDownload, FiEdit2, FiFileText, FiPlus, FiPower,
  FiRefreshCw, FiSearch, FiServer, FiShield, FiTrash2, FiUsers, FiXCircle,  // FiShield added
} from 'react-icons/fi';
```

After the closing `</div>` of `nm-node-main` (currently the last element before `</Card>`), add the conditional meta row. The exact insertion point is after line ~410 where `nm-node-main` closes:

```tsx
{(health !== 'online' || tls.tone === 'warning' || tls.tone === 'danger') && (
  <div className="nm-node-meta">
    {health === 'offline' && (
      <span className="nm-meta-chip nm-meta-chip--danger">
        <FiXCircle size={11} aria-hidden="true" />
        {t('statusOffline', 'Offline')}
      </span>
    )}
    {health === 'warning' && (
      <span className="nm-meta-chip nm-meta-chip--warn">
        <FiXCircle size={11} aria-hidden="true" />
        {t('nodeUnreachable', 'Unreachable')}
      </span>
    )}
    {(tls.tone === 'warning' || tls.tone === 'danger') && (
      <span className={`nm-meta-chip nm-meta-chip--${tls.tone === 'danger' ? 'danger' : 'warn'}`}>
        <FiShield size={11} aria-hidden="true" />
        {tls.label}
      </span>
    )}
  </div>
)}
```

No new i18n keys needed — `t('statusOffline')`, `t('nodeUnreachable')`, and `tls.label` (which uses existing `t('tlsSelfSigned')`, `t('tlsPlain')`) are all already declared.

**File:** `web/src/pages/NodeManagement.css`

Append after the existing `.nm-node` modifier rules:

```css
/* Meta row: only shown on degraded nodes. Healthy nodes produce no row. */
.nm-node-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4) var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.nm-meta-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-2);
  border-radius: var(--radius-xs);
  font-size: var(--font-size-2xs);
  font-weight: var(--font-weight-semibold);
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
}

.nm-meta-chip--danger {
  background: var(--danger-soft);
  color: var(--danger-text);
}

.nm-meta-chip--warn {
  background: var(--warning-soft);
  color: var(--warning-text);
}
```

**Self-check:**
```bash
grep -n "nm-node-meta\|nm-meta-chip" web/src/pages/NodeManagement.css web/src/pages/NodeManagement.tsx
# Both files must show the new selectors/JSX

cd web && npm run check:rtl    # flex + gap is RTL-safe — must pass
cd web && npm run verify

# i18n check: confirm no new keys were introduced
cd web && npm run check:i18n   # must pass clean
```

---

### Task 3.3 — Node drawer: fixed footer so close/actions are always visible

**Context:** `NodeDrawer.tsx` is 623 lines. The drawer renders as a full-height right panel. Currently the drawer body (`node-drawer-body`) scrolls, but there is no fixed footer — the close button is only in the header, and the header stays visible, so this is not as bad as initially thought. The actual problem: primary actions (Edit, Download) are only accessible via the list row action buttons *outside* the drawer. An operator with the drawer open for a long log tab has to close the drawer and find the button in the list. A footer fixes this.

The structural change is minimal — add one `<div>` at the bottom of the drawer JSX and style it as a fixed footer.

**File:** `web/src/components/NodeDrawer.tsx`

Find the bottom of the drawer JSX, just before the outer wrapper `</div>` closes (around line 620). The drawer body closes somewhere before the drawer wrapper. Insert after `</div>` that closes `node-drawer-body`, before the outer closing tag:

```tsx
<div className="node-drawer-footer">
  <Button
    variant="secondary"
    size="sm"
    icon={<FiEdit2 size={14} />}
    onClick={onEdit}
  >
    {t('editButton', 'Edit')}
  </Button>
  <Button
    variant="primary"
    size="sm"
    icon={<FiDownload size={14} />}
    onClick={onDownloadAll}
  >
    {t('downloadAll', 'Download all')}
  </Button>
</div>
```

Check the existing props interface at the top of `NodeDrawer.tsx` for `onEdit` and `onDownloadAll` (or equivalent). If they don't exist as props, check what the drawer already does for these actions — there may be internal buttons already in the drawer tabs. If internal tab buttons already provide Edit and Download, **skip the footer button addition** and only add the footer CSS for layout structure with a close reminder button:

```tsx
<div className="node-drawer-footer">
  <Button variant="secondary" size="sm" onClick={onClose}>
    {t('close', 'Close')}
  </Button>
</div>
```

The key UX requirement is: *something actionable is always visible at the bottom of the drawer without scrolling.*

**File:** `web/src/components/NodeDrawer.css`

Add after the existing `.node-drawer-body` rule:

```css
.node-drawer-body {
  /* existing rules — ensure these two are present: */
  flex: 1;
  min-height: 0;   /* critical: flex children won't scroll without this */
  overflow-y: auto;
}

.node-drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border);
  background: var(--surface-1);
  flex-shrink: 0;
}
```

Also ensure `.node-drawer` itself is `display: flex; flex-direction: column; height: 100dvh;` — check the existing rule. If `height: 100dvh` is not there, add it.

**Self-check:**
```bash
grep -n "node-drawer-footer\|flex-shrink\|min-height: 0" web/src/components/NodeDrawer.css
# Must show all three

cd web && npm run verify

# Visual: open any node drawer, scroll the body to the bottom of a long tab (logs)
# Footer must be visible at the bottom at all times
# Header (with node name and × close) must be visible at the top at all times
```

---

## Final verification — run once after all phases complete

```bash
# 1. Structural check
wc -l web/src/styles.css
# Target: ≤ 150 lines (down from 3018)

# 2. CSS cleanliness
grep -c "!important" web/src/styles.css
# Target: ≤ 15 (down from 71)

# 3. No legacy buttons
grep -rn "\"btn \|\"btn\"\| btn btn\| btn-sm\| btn-danger\| btn-secondary\| btn-success\| btn-primary" web/src --include="*.tsx"
# Must return zero

# 4. No hardcoded hex in component CSS
grep -rn "#[0-9a-fA-F]\{3,6\}" web/src --include="*.css" | grep -v "tokens.css\|fonts.css\|/* rtl-ok\|/* hardcoded-ok"
# Review every remaining hit — each must be intentional (e.g., a specific shadow value, not a color token)

# 5. Full CI gate
cd web && npm run verify
# Must pass: build + check:tokens + check:i18n + check:rtl + eslint + tsc + 81 vitest tests

# 6. Go side untouched
cd /root/workspace/OVManager && make lint && go test ./...
# Must pass clean

# 7. Visual regression
# Screenshot all 9 routes in dark mode and light mode
# Check all with accent picker set to: Orange (default), Indigo, Emerald
# The KPI meter bars must be cyan (not orange) on neutral tiles
# The body background gradient must shift subtly when accent changes
# Node list: green/amber/red left borders on cards by health state
# Node list: meta row visible on degraded/TLS-warn nodes, absent on healthy nodes
# Node drawer: footer always visible
```

---

## What this plan does NOT include

**Explicitly out of scope — do not add these:**

- Font replacement (Manrope is already correctly self-hosted with subset coverage for all 4 locales)
- `--brand` token split from `--accent` (the accent picker makes this incoherent)
- UserManagement.tsx redesign (architecturally sound, out of scope)
- NodeDrawer full rewrite into typed sub-components (separate project)
- Light-mode design pass (token system already handles it)
- Mobile layout changes (bottom nav and off-canvas sidebar are correct)
- Any Go backend changes
- New npm dependencies
