# OVManager design direction

One page, so a UI change can be judged against intent instead of taste.

## Identity

A fleet operations console: dense, calm, built for someone watching live
sessions and traffic at 2 a.m. It should read as a tool, not a landing page.

## Palette

- Dark default, with a working light theme. An ops console is used for long
  stretches and often in low light; that is the reason, not "dark looks tech".
- One accent: orange (`--accent`, `#ff6a1a`). It marks the current section,
  primary actions, and focus. It does not mark hover.
- Status uses separate fill and text tones (`--success` vs `--success-text`,
  etc.) so a vivid hue never has to carry body text. Every pair is AA-checked
  in `tokens.css`; do not add a raw hex outside that file.
- Hover is neutral (`--surface-hover` + `--text-primary`). Accent on every
  hover made the whole page shout and blurred the active state.

## Typography

- Manrope for UI text, Space Grotesk for the wordmark and display numbers.
  Manrope stays legible at 12 to 13px table density; Space Grotesk gives the
  brand a distinct voice without a second UI face.
- Numbers in tables use tabular figures so columns line up.

## Layout

- Fixed topbar (64px) + collapsible sidebar (220px, 72px rail). Content is
  capped at 1480px.
- Tables scroll inside their own box; the page never scrolls sideways.
- Density is a feature: 34 to 36px rows, 12 to 13px labels.
- Mobile: bottom tab bar, off-canvas sidebar, 44px minimum touch targets.

## Motion

Hover and focus transitions only (150 to 250ms). No scroll reveals, no
parallax. Live data already moves; decoration on top of it would compete.
All motion stops under `prefers-reduced-motion`.

## Dials

ENERGY 1 / RHYTHM 1 / MOTION 1. Calm and uniform on purpose: the content is
the event, and a predictable grid is what makes an outlier (an offline node,
a quota alert) visible.

## Rules for new work

- Use the tokens in `web/src/tokens.css`; no new palette.
- One focal point per screen.
- Every data view ships empty, loading, and error states.
- Icon plus label beats a dot plus label. One signal per status.
