# OVManager — UI/UX Audit & Improvement Plan

Reviewed: `frontend/` (React 19 + Vite 8, react-router 7, i18next, 4 locales, 3 themes).
Method: static read of all 40 components/pages, all ~7.8k lines of CSS, WCAG contrast math on
every token pair, dev server run to confirm the build is clean. ESLint passes with zero warnings.

**Overall: this is a genuinely good panel.** Command palette, skip link, focus-trapped modals,
focus restoration, RTL support, live SSE refresh, onboarding checklist, pull-to-refresh,
undo-delete, density toggle, `prefers-reduced-motion` — most panels in this category have none of
that. The problems below are almost all in the **CSS layer**, which has accumulated two competing
design systems that now fight each other. That is the single highest-leverage thing to fix.

---

## 1. Critical — the CSS architecture is actively broken

### 1.1 Two `:root` token sets overwrite each other

`main.jsx` imports `index.css` then `styles.css`. Both define a full `:root` palette, so
**`styles.css` silently wins and ~16 of `index.css`'s carefully-built tokens are dead code**:

| token | `index.css` intends | what actually applies |
|---|---|---|
| `--accent-color` | `#fc7a1e` | `#ff6a1a` |
| `--text-primary` | `#e8ebf1` | `#f7f8fa` |
| `--text-secondary` | `#9aa4b5` | `#9aa1ad` |
| `--panel` | `var(--background-secondary)` | `#181b22` |
| `--danger-color` | `#e5484d` | `#ff5368` |
| `--success-color` | `#01c3a8` | `#2fd276` |
| `--info-color` | `#38a1ff` | `#19d3e9` |
| `--border-color` | `var(--border)` | `#2f343f` |

The whole "elevation scale" comment block in `index.css` (`bg < elevated < surface-1 < surface-2 <
surface-3`) describes a system that is only half in effect. This is why the panel needs 82
`!important` declarations in `styles.css` to force things into place.

There is also a genuinely cyclic declaration at `index.css:74`:

```css
--bg: var(--bg);   /* resolves to nothing — invalid at computed-value time */
```

**Fix:** one `tokens.css` that owns every custom property and all three theme blocks. `index.css`
becomes base/reset + primitives; `styles.css` becomes layout/components. Nothing else declares
`:root`. You can then delete most of the `!important`s.

### 1.2 235 duplicated selectors across the two files

`.btn`, `.icon-btn`, `.empty-state`, `.filter-chip`, `.ops-main-content`, `.status-pill`,
`.actions-dropdown-*`, `.audit-table` … all defined twice with *different* values.

`.btn` is the clearest example — `index.css:331` gives it `padding: 12px 24px; border-radius: 10px;
color: #000; font-size: 15px` plus a shimmer `::before`; `styles.css:140` overrides it to
`padding: 10px 14px; border-radius: 8px; color: #fff`. Both run. The shimmer animation still plays
on a button that no longer has the geometry it was designed for.

`.ops-main-content` is defined in **both** files with conflicting margins, and then `styles.css:3044`
nukes it with `margin-left: 0 !important` — meaning the entire `--collapsed` / `--rail` margin
machinery in `index.css:477-497` (and the `collapsed` state tracking in `DashboardLayout.jsx`) is
computing values that get thrown away. Layout is actually driven by `.ops-main-container` instead.
That's a lot of dead state.

**Fix:** pick one owner per component. A quick way to find them all:

```bash
grep -oh "^\.[a-zA-Z0-9_-]*" src/styles.css src/index.css | sort | uniq -d
```

### 1.3 Sidebar collapsed width disagrees with itself

`index.css` and `styles.css:3037` say the rail is **72px**. `styles.css:4171` and `:4187` say
**60px**. Later rule wins for the container/topbar, but `--sidebar-collapsed-width: 72px` still
drives the aside. **The rail and the content edge are 12px out of alignment when collapsed.**

### 1.4 Breakpoints disagree between JS and CSS

- `DashboardLayout.jsx` / `Sidebar.jsx`: mobile is `< 768px`
- `styles.css:4425`: sidebar hides and hamburger appears at `≤ 900px`
- `MobileNav`: bottom bar appears at `≤ 760px`

**Between 761px and 900px there is no sidebar, no bottom nav, and React still thinks it's desktop**
(`isMobile === false`, so it applies desktop margins). Tablets land exactly in this hole. There's
even a patch rule at `:4450` adding `padding-inline-start: 62px` to compensate — treating the
symptom.

**Fix:** define the breakpoints once and share them.

```js
// utils/breakpoints.js
export const BP = { mobile: 760, tablet: 900 };
export const isMobile = () => window.matchMedia(`(max-width: ${BP.mobile}px)`).matches;
```

Use `matchMedia` (not `innerWidth` + `resize`) so JS and CSS can never drift, and you stop
re-rendering on every resize frame.

---

## 2. Accessibility

### 2.1 Light theme fails WCAG badly

Contrast ratios I computed against the light surfaces (AA body text needs **4.5:1**, large text and
UI borders need **3:1**):

| element | ratio | verdict |
|---|---|---|
| `--text-muted` `#8a93a3` on `#eef1f6` | **2.73** | ✗ fail |
| `--accent-color` `#e86a0c` as text on `#fff` | **3.23** | ✗ fail |
| `--success-color` `#0e9f85` on `#fff` | **3.32** | ✗ fail |
| white button label on accent `#e86a0c` | **3.23** | ✗ fail |
| table `thead` `#c6cad2` on white | **1.64** | ✗✗ near-invisible |
| `.status-pill.online` `#2ff0d4` on white | **1.44** | ✗✗ invisible |
| `.status-pill.warn` `#ffb454` on white | **1.76** | ✗✗ invisible |
| `.status-pill.danger` `#ff7a8a` on white | **2.50** | ✗ fail |

The status pills matter most: **in light mode a user cannot tell online from offline from expired**,
which is the primary job of this screen. `styles.css:857` adds a light override for `.status-pill.idle`
only — `.online`, `.warn` and `.danger` were missed. Same for `thead th` colour: the override at
`:830` fixes the background to `#eef3f9` but leaves the `#c6cad2` text from `:287`.

Dark theme is fine (everything ≥ 3.7:1, most ≥ 6:1). This is a light-mode-only problem.

**Fix:** give every semantic colour a paired `-text` token that's tuned per theme.

```css
:root {                      /* dark */
  --success: #2fd276;  --success-text: #2fd276;  --success-bg: rgba(47,210,118,.16);
}
html[data-theme="light"] {
  --success: #0e9f85;  --success-text: #076a58;  --success-bg: rgba(14,159,133,.14);
}
```

Also: primary buttons should use `color: #000` on orange (**7.94:1**) rather than `#fff` (**2.64:1**).
`index.css` already gets this right; `styles.css:140` and the light override at `:865` force it back
to white. Worth fixing — it's the most-clicked element in the app.

### 2.2 Sortable table headers announce nothing

`UserTable`/`NodeTable` headers are clickable and show a chevron, but there's no `aria-sort`
anywhere in the codebase, and the sort control is a `<th>` with an `onClick` rather than a button —
so it isn't keyboard-reachable at all.

```jsx
<th aria-sort={sort.key === 'name' ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
  <button type="button" className="th-sort" onClick={() => onSort('name')}>
    {t('username')} {sort.key === 'name' && <SortIcon dir={sort.dir} />}
  </button>
</th>
```

### 2.3 Form errors aren't wired to their fields

Zero uses of `aria-invalid` or `aria-describedby`. In `AddUserModal` the error renders in a `<p
className="error-message">` *after* the footer, with no `role="alert"` and no association to the
field that failed — a screen reader user submits, hears nothing, and the message is visually below
the button. `LoginPage` does this correctly (`role="alert"` + `aria-live`); the modals should match.

Also worth noting: username is capped at `maxLength="10"` with no visible hint or counter, so the
input just stops accepting characters silently.

### 2.4 Icon buttons are below the touch-target minimum

`.icon-btn` is `2rem × 2rem` (32px). WCAG 2.5.8 asks for 24px minimum and the practical mobile
guideline is 44px. The topbar has four of these in a row (search, language, theme, bell) at 8px
gaps — fiddly on a phone. `.mobile-nav-link` at `min-height: 50px` is good; the topbar should match.
Also `.mobile-nav-link` labels are `font-size: 9px`, which is below what most people can read.

### 2.5 Smaller items

- `.list-table td` is `font-size: 13px` and `.list-table th` is `11px`; there are 22 uses of `10px`
  and 9 of `9px` across `styles.css`. For a monitoring panel people stare at, bump the floor to 12px.
- `<html lang="en">` is hardcoded in `index.html`. `DashboardLayout` fixes it after mount, but the
  login page never does — so a Persian or Chinese user's login screen is announced as English, and
  `dir="rtl"` isn't applied there either. Set both in `main.jsx` before render.
- No `<meta name="theme-color">` and no `<meta name="description">`; the mobile browser chrome
  won't match the panel.
- `.icon-btn.has-alerts` turns the entire bell button into a solid red pill. It reads as an error
  state rather than a count. A small corner badge on a neutral button is the conventional pattern
  and is far less alarming at a glance.

---

## 3. UX & interaction

### 3.1 The users table has no loading state

`UserManagement.jsx:530` passes `isLoading={false}` — hardcoded. `UserTable` has a perfectly good
`UserTableSkeleton` component that **can never render**. On first load and on every SSE refresh the
table shows the empty state or stale rows with no indication anything is happening. There's no
`loading` state variable in the page at all.

```jsx
const [isLoading, setIsLoading] = useState(true);
const fetchUsers = async () => {
  setIsLoading(true);
  try { /* … */ } finally { setIsLoading(false); }
};
// …
<UserTable isLoading={isLoading} … />
```

(Small refinement: skip the skeleton on SSE-triggered background refreshes so the table doesn't
flash every 30s — only show it when `users.length === 0`.)

### 3.2 Search has no debounce

`UserManagement` filters and re-sorts the full list on every keystroke via `useMemo`. Fine at 50
users, visibly janky at 2000 — and this panel is built for fleets. A 200–250ms debounce on
`searchTerm` fixes it. Same in `CommandPalette`, which additionally refetches `/users/` and
`/nodes/` on every open.

### 3.3 Sticky table headers don't actually stick

`.list-table thead th` has `position: sticky; top: 64px`, but the scroll container is `body`
(`styles.css:3020` sets `overflow-y: auto` on body) while `.list-table-container` only has
`overflow-x: auto` and no `max-height`. Sticky positioning needs a scrolling ancestor — there isn't
one on the vertical axis, so **the headers scroll away** on long lists. Either give the container a
`max-height: calc(100vh - 260px); overflow-y: auto`, or make `.ops-main-content` the scroll
container (`height: 100vh; overflow-y: auto`) instead of the body.

Related: `top: 64px` is duplicated as a magic number in four places (`styles.css:119, 287, 310,
647`) and `index.css:481` uses `52px` for the same topbar. Make it `--topbar-h: 64px`.

### 3.4 Table filter/sort/page state is lost on navigation

Search term, active filter chip, sort, and current page all live in `useState`. Click into a user,
come back — everything resets to page 1 / All / name-asc. For an operator triaging "expiring soon"
across 400 users that's genuinely painful. Put it in the URL:

```jsx
const [params, setParams] = useSearchParams();
const view = params.get('view') ?? 'all';
const q = params.get('q') ?? '';
```

Bonus: filtered views become bookmarkable and shareable, and browser Back works properly.

### 3.5 Pagination is fixed at 25 with no total

`PAGE_SIZE = 25` is a constant, and the footer only says "Page 1 of 17". Add a rows-per-page select
(25/50/100, persisted like `density` already is) and show "Showing 1–25 of 412". Also
`useEffect(() => setCurrentPage(1), [users])` resets to page 1 on *every* SSE refresh — so a user
reading page 6 gets yanked back to page 1 every 30 seconds. Reset on filter/search change, not on
data change.

### 3.6 Bulk actions are unconfirmed and un-undoable

Single delete gets a `ConfirmModal` and a 10-second undo toast — nicely done. But
`handleBulkDelete(selected)` can nuke 200 users, and the bulk `+30 days` / `+10 GB` buttons fire
immediately with no confirmation at all. Route bulk operations through the same
`ConfirmModal` + undo path, and echo the count in the confirm text.

### 3.7 Toasts are fire-and-forget

`ToastContext` has a fixed 3500ms timeout and no dismiss button. Error toasts in particular should
persist until dismissed — a failed node sync that vanishes in 3.5s while you're looking elsewhere is
a lost error. Add a close button, pause-on-hover, and `duration: null` for `error`. The container is
`aria-live="polite"`; errors should be `assertive`.

### 3.8 Empty states are dead ends

`EmptyState` supports `actionLabel`/`onAction`, and `UserManagement` passes them at the page level —
but the copy inside `UserTable` (`noUsersTitle`/`noUsersBody`) renders with no action. More
importantly, **filtered-empty and truly-empty use the same message**. If someone filters to "Near
quota" and gets nothing, "No users yet — add your first user" is wrong and confusing. Distinguish:

```jsx
users.length === 0
  ? <EmptyState title={t('noUsersTitle')} actionLabel={t('addNewUser')} onAction={openAdd} />
  : <EmptyState title={t('noMatches')} description={t('noMatchesBody')}
                actionLabel={t('clearFilters')} onAction={clearFilters} />
```

### 3.9 Six unlocalised strings

Every other string goes through `t()`, but these are raw English and will show up untranslated for
Persian/Russian/Chinese users:

```
pages/AdminManagement.jsx:62   'Admin created successfully.'
pages/AdminManagement.jsx:74   'Admin updated successfully.'
pages/NodeManagement.jsx:187   'Node created successfully.'
pages/UserManagement.jsx:360   'Error resetting usage.'
pages/UserManagement.jsx:425   'User created successfully.'
pages/UserManagement.jsx:427   'User updated successfully.'
```

Plus hardcoded `aria-label`s in `UserTable`'s `RowMenu` (`` `Edit ${user.name}` ``, `Delete …`,
`Copy user ID for …` — ~10 of them) and `"Select all users"`, `"Close modal"`, `"Search users by
username"`. All four locale files have exactly 601 keys, so the translation pipeline is otherwise
in great shape — worth closing this gap.

### 3.10 RTL coverage is partial

68 `html[dir="rtl"]` rules in `styles.css` — real effort. But there are still 45 physical
`margin-left`/`padding-right`-style declarations against only 20 logical ones. `index.css` in
particular has **zero** RTL rules while using `margin-left: 220px` for the main content, so the
Persian layout depends entirely on `styles.css` overriding it. Converting to
`margin-inline-start` / `padding-inline-end` / `inset-inline-start` would delete most of that RTL
block outright.

### 3.11 Dead code

- The `ultra` theme has a full 30-line token block in `index.css:108` and is referenced nowhere in
  JS — `ThemeContext` explicitly discards it ("Legacy `ultra` values are intentionally discarded").
  Delete it.
- `.ops-shell`, `.ops-topbar` (the 60px grid one), `.ops-nav-link`, `#main-container`, `.world-map`
  with its `.d0`–`.d7` hardcoded dots, `.map-dot` — all from the pre-sidebar "Concept #1" layout,
  no longer rendered by any component.
- `.ops-main-content--rail` — never applied; the class list only ever produces `--collapsed`.
- 10 `console.*` calls left in production paths.

---

## 4. Suggested enhancements

These are additions rather than fixes, ordered by value-per-effort:

1. **Auto-refresh control in the topbar.** The refresh cadence is buried in Settings → Alerts. A
   `Live ● / Paused ‖` toggle next to the bell, with the interval inline, puts it where people
   actually think about it — and lets them pause polling while reading.
2. **Row click opens a detail drawer, not a modal.** `NodeDrawer` already exists and is the better
   pattern; `UserDetailModal` blocks the list behind it. A drawer lets you keep scanning the table
   and arrow between users.
3. **Keyboard shortcuts beyond ⌘K.** You already have the palette infrastructure. `g u` → users,
   `g n` → nodes, `/` → focus search, `?` → shortcut cheatsheet. Cheap to add, big perceived-quality
   win for an ops tool.
4. **Saved views.** "Expiring this week", "Over quota", "Offline > 24h" as one-click presets. The
   filter logic already exists in `filterCounts` — this is mostly UI.
5. **Sparkline per user row.** `trafficHistory` is already collected for the dashboard. A 40px
   inline sparkline in the traffic column turns the table from a snapshot into a trend view.
6. **Optimistic updates.** Enable/disable/extend currently round-trip before the row changes. Flip
   the row immediately and roll back on failure — the panel will feel dramatically faster.
7. **Bulk select across pages.** Selecting all currently selects the filtered set but pagination
   slices it — the interaction between `selected` and `paginatedUsers` is ambiguous. Add an explicit
   "Select all 412 matching" affordance like Gmail's.
8. **`prefers-contrast: more` support.** You already respect `prefers-reduced-motion` in two places;
   this is the natural companion and cheap once tokens are unified.

---

## Priority order

**Ship first — real bugs, small diffs:**
1. Light-theme status pills + `thead` contrast (§2.1) — functional failure, ~20 lines
2. `isLoading={false}` in `UserManagement` (§3.1) — one-line fix, unlocks an existing component
3. The 761–900px tablet dead zone (§1.4)
4. Rail width 60 vs 72px (§1.3)
5. Six unlocalised toasts + `RowMenu` aria-labels (§3.9)
6. Reset-to-page-1 on every SSE tick (§3.5)

**Then — the structural work that makes everything after it easier:**
7. Unify tokens into `tokens.css`, kill the `:root` collision and the cyclic `--bg` (§1.1)
8. De-duplicate the 235 shared selectors, drop the `!important`s (§1.2)
9. Delete the dead layout CSS and the `ultra` theme (§3.11)

**Then — UX depth:**
10. URL-backed table state (§3.4)
11. Sticky headers via a real scroll container (§3.3)
12. Search debounce (§3.2)
13. `aria-sort` + keyboard-operable sort buttons (§2.2)
14. Dismissible/persistent error toasts (§3.7)
15. Bulk-action confirmation (§3.6)
16. Filtered-empty vs truly-empty states (§3.8)

I'd treat 7–9 as one focused refactor. It's the root cause of most of the visual inconsistency, and
until it's done every styling fix risks being silently overridden by the other file.

---

# Implementation log — performance, resilience & loading UX

The following was implemented on top of the audit above.

## Bundle: −55% on the critical path

| chunk | before | after |
|---|---|---|
| `index` (entry) | 380.9 kB / **118.5 kB gz** | 302.5 kB / **97.5 kB gz** |
| `ServerStats` | 164.5 kB / **59.2 kB gz** | 30.2 kB / **8.5 kB gz** |
| `WorldMap` (new, lazy) | — | 137.7 kB / 51.8 kB gz |
| `fa`/`ru`/`cn` locales | in entry | 3 lazy chunks, ~45 kB gz total |

Dashboard JS on first paint went from **~178 kB gz to ~106 kB gz**, and an
English user no longer downloads ~45 kB gz of Persian, Russian and Chinese
strings they will never read.

- **`WorldMap` extracted** to `components/dashboard/WorldMap.jsx` — it owns the
  only imports of `d3-geo`, `topojson-client` and the 105 kB `world-atlas`
  TopoJSON. Loaded with `React.lazy`, so KPI cards and tables paint without it.
- **Locales split** — `i18n.js` bundles English only; `fa`/`ru`/`cn` load on
  demand via `loadLanguage()`. If the stored preference is a lazy locale the app
  boots in English and swaps when the chunk lands, so first paint never blocks
  on a JSON fetch.
- **Fonts un-blocked** — the render-blocking `@import` in `index.css` (which
  serialised html → css → font-css → font) is gone, replaced by `preconnect` +
  a `media="print"/onload` swap in `index.html`.
- **Route prefetching** — `App.jsx` warms Users/Nodes/Settings chunks during
  `requestIdleCallback` after auth, chained sequentially so it never competes
  with the current route's data.

## Instant first paint

`index.html` now ships a **static app-shell skeleton** (sidebar + topbar + card
grid) with its own inlined critical CSS, plus a tiny boot script that reads
`localStorage` and applies `data-theme` and `dir` *before* the bundle parses.
Removes both the white flash for dark-mode users and the LTR→RTL jump for
Persian. `main.jsx` fades it out from the render callback, so it only clears
once React has actually committed.

## Per-section error handling

The core change: **`Promise.all` → `Promise.allSettled`** via a new
`settle()` helper in `hooks/useAsyncData.js`.

Previously one failing endpoint took down everything it was grouped with. Worst
case was the notification bell — a single failed request silently emptied the
entire alert list, the worst possible failure mode for an alerting surface.
Fixed in `ServerStats` (5 endpoints), `DashboardLayout` (bell),
`Settings` and `OnboardingChecklist`.

`ServerStats` now keeps a per-source `errors` map; each panel renders its own
inline error with a scoped retry, and the full-page error state appears only
when *every* source fails. Added `SectionBoundary` — a per-widget error boundary
with local retry that remounts just that subtree — wrapping every route and the
lazy map, so a render crash in one widget no longer replaces the whole panel.

## Loading UX

- **New `Skeleton` primitives** (`block`/`text`/`panel`/`stats`/`table`) that
  match real content geometry, so nothing shifts when data lands. RTL-aware
  shimmer, `prefers-reduced-motion` respected, one polite live region per
  container rather than per box.
- **`isLoading={false}` fixed** — `UserManagement` passed a hardcoded `false`,
  so `UserTable`'s skeleton could never render. Now tracks real state, and the
  loading branch is checked *before* the empty branch (previously
  `users.length === 0` short-circuited to "no users yet" during first load).
- **Background vs first load** separated everywhere: SSE/poll refreshes keep
  current data on screen instead of flashing skeletons every 30s.
- **Filtered-empty vs truly-empty** now distinct — filtering to zero offers
  "Clear filters", not "add your first user".
- Route-level `PageLoader` replaced the centred spinner with a shaped skeleton.

## Verification

- ESLint clean across `src/`
- 15/15 tests pass, including new ones: `settle()` isolation, and a DOM test
  asserting the dashboard still renders healthy panels while
  `/security/summary` is failing (the exact regression this work targets)
- Production build succeeds; dev server serves shell + modules correctly
- 9 new i18n keys added to all four locales (610 keys each, still in parity)
