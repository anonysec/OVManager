# Usermanagement Page Overrides

> **PROJECT:** OVManager
> **Generated:** 2026-10-16 05:00:25
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- No overrides — use Master colors

### Component Overrides

- Avoid: Wide tables breaking layout
- Avoid: Use arbitrary large z-index values
- Avoid: Blank screen or '0 results'

---

## Page-Specific Components

- **Cell density:** table cells use the 4px grid (`--space-2` / `--space-3`
  padding, rows min `--row-h`) — dense but not cramped.
- **Overflow:** username/tag cells ellipsize; the row link carries a `title`
  with the full name + uuid. Long tags cap at 120px with ellipsis.
- **Status:** badges map through Master status rules — online → `--success`,
  idle → `--info`, expiring → `--warning`, disabled/expired → `--danger`.
  Fill/text/soft split per Master; no hex on this page.
- **375px:** the table scrolls inside its own `.dt-scroll` container
  (never the page); the swipe hint announces the hidden columns.
- **Touch targets:** row/pager icon buttons keep a 30px visual but expand to
  a ≥44px hit area via a pseudo-element (no row bloat); filter chips and row
  menu items go to `--control-h-lg` (44px) on coarse pointers / phones.

---

## Recommendations

- Effects: Purposeful admin feedback and restrained transitions
- Responsive: Use horizontal scroll or card layout
- Layout: Define z-index scale system (10 20 30 50)
- Search: Show 'No results' with suggestions
