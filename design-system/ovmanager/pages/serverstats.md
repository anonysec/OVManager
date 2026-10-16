# Serverstats Page Overrides

> **PROJECT:** OVManager
> **Generated:** 2026-10-16 04:54:47
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1400px or full-width
- **Grid:** 12-column grid for data flexibility

### Spacing Overrides

- **Content Density:** High — optimize for information display

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- No overrides — use Master colors

### Component Overrides

- No overrides — use Master component specs

---

## Page-Specific Components

- **KPI rail hierarchy:** the first four cells of `.ds-stats-grid` are lead
  counters (value at `--font-size-2xl`); later cells are utilization gauges
  (value at `--font-size-lg`, label at `--text-muted`). Position-based —
  keep lead counters first in DOM order; KpiCard needs no extra prop.
- **Chart legend:** series marks are explained by a text legend below the
  chart — shape + label, never colour alone.
- **States:** every loading skeleton and empty state in this page carries
  `role="status"` so screen readers announce it. All colours come from
  Master tokens (no hex on this page).

---

## Recommendations

- Effects: Hover tooltips, chart zoom on click, row highlighting on hover, smooth filter animations, data loading spinners
