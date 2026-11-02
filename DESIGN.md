# DESIGN.md

## Product
Admin dashboard for OVManager: ops/monitoring control plane for OpenVPN nodes and users.

## Tone
Calm / minimal. Low noise, high clarity. No decorative flourish.

## Theme
System-aware: light default, dark available via toggle. Respect prefers-color-scheme. Multi-theme accent: user can choose accent color in settings (orange, blue, green, etc.); all accents must pass contrast checks.

## Typography
- UI: Manrope (body) + Space Grotesk (display), two weights each. No more.
- Data/numbers: tabular monospace for IPs, CNs, timestamps.
- Scale: 12/14/16/20/24. No arbitrary sizes.

## Color
- Neutral base: slate scale. Accent is user-selectable from a curated palette (orange, blue, green); one accent active at a time.
- Status: green (ok), amber (warn), red (error). Never decorative color.
- No gradients on surfaces, no glassmorphism, no colored left stripes. Accent gradients allowed only on primary CTA if purpose-tested.

## Layout
- Sidebar: compact icon+label, dense, more items visible. Main content area.
- Compact data tables with comfortable row padding. Generous whitespace between sections.
- No bento grids. No card-per-metric unless the metric needs isolation.
- Theme switcher lives in settings; default follows system.

## Motion
- Subtle only: 150ms ease for hover/focus and panel open. No entrance animations on data.

## Components
- Buttons: solid primary, ghost secondary. No pill badges as decoration.
- Forms: inline labels, clear validation states.
- Tables: sticky header, zebra only if needed, row hover.

## Accessibility
- Contrast >= 4.5:1 text. Keyboard navigable. Visible focus rings. No zoom ban.
