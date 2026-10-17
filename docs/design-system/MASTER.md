# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

## Verdict (Step 2b verification)

> Rewritten 2026-10-16 from the shipped theme. **Single source of truth:
> `frontend/src/tokens.css`.** This file documents those tokens; never invent
> values here that tokens.css does not declare. (Supersedes the generated
> draft, which described a different theme than the app ships.)

1. Style: **Dark ops console** — fits a dense RTL-capable internal monitoring console for a solo homelab admin.
2. Dark surfaces with a stepped elevation ladder (`--bg` → `--bg-elevated` → `--surface-1/2/3`) keep tables and panels quiet under long sessions; light theme repaints the ladder via `html[data-theme="light"]`.
3. Accent is **orange `#ff6a1a`** (`--accent`) for nav/active states, primary buttons, focus rings and CTA — black ink `#15110a` sits on orange fills (7.9:1), never white.
4. Status colors are semantic and split **fill vs text**: `--success` / `--warning` / `--danger` / `--info` carry dots, bars and fills; the paired `--*-text` tones carry labels and pill text (AA in both themes).
5. Fonts: **Manrope** (body, `--font-family`) + **Space Grotesk** (display, `--font-display`) — self-hosted under `/fonts/`, no CDN.
6. RTL caveat: neither font carries Arabic/Persian glyphs; the fa locale falls back to system fonts — add a fa fallback (e.g. Vazirmatn) to the stack when fa typography matters.
7. Density: 4px spacing grid (`--space-1`…`--space-10`), dense row height `--row-h: 34px`, control heights 30/38/44px — touch targets stay ≥44px (`--control-h-lg`).
8. Motion: subtle only — `--transition-fast` 150ms / `--transition-normal` 250ms / `--transition-slow` 400ms, `prefers-reduced-motion` respected.
9. Light + dark both supported; light mode darkens every `--*-text` tone to clear 4.5:1 on `#ffffff` and `#eef1f6`.
10. Noted mismatch: the generated output pattern is marketing "Hero + Features + CTA" — reuse its structural ideas only; ignore hero/CTA sections for the admin console.

---

**Project:** OVManager
**Source of truth:** `frontend/src/tokens.css` (shipped 2026-10-16)
**Category:** General
**Design Dials:** Variance 4/10 (Balanced / Modern) | Motion 3/10 (Subtle) | Density 8/10 (Dense / Dashboard)

---

## Global Rules

### Color Palette — dark (default, `color-scheme: dark`)

| Role | Value | CSS Variable |
|------|-------|--------------|
| Accent / primary action | `#ff6a1a` | `--accent` |
| Accent hover | `#ff7e2e` | `--accent-hover` |
| Accent active | `#e85b0f` | `--accent-active` |
| Accent wash | `rgba(255,106,26,0.12)` | `--accent-soft` |
| Accent border | `rgba(255,106,26,0.35)` | `--accent-border` |
| Ink on accent fill | `#15110a` | `--accent-contrast` |
| Background | `#0e1116` | `--bg` |
| Background elevated | `#131722` | `--bg-elevated` |
| Surface 1 / 2 / 3 | `#181b22` / `#1f232c` / `#2a3144` | `--surface-1/2/3` |
| Inset well / hover wash | `#12151c` / `#232833` | `--surface-inset` / `--surface-hover` |
| Border / strong / subtle | `#2f343f` / `#3d465c` / `#262b35` | `--border` / `--border-strong` / `--border-subtle` |
| Text primary / secondary / muted | `#f7f8fa` / `#9aa1ad` / `#838a96` | `--text-primary` / `--text-secondary` / `--text-muted` |
| Success (fill) / text / soft | `#2fd276` / `#2fd276` / `rgba(47,210,118,0.16)` | `--success` / `--success-text` / `--success-soft` |
| Warning (fill) / text / soft | `#ffb454` / `#ffb454` / `rgba(255,180,84,0.16)` | `--warning` / `--warning-text` / `--warning-soft` |
| Danger (fill) / text / soft | `#ff5368` / `#ff7a8a` / `rgba(255,83,104,0.16)` | `--danger` / `--danger-text` / `--danger-soft` |
| Info (fill) / text / soft | `#19d3e9` / `#19d3e9` / `rgba(25,211,233,0.16)` | `--info` / `--info-text` / `--info-soft` |
| Ink on success/danger fill | `#15110a` | `--success-contrast` / `--danger-contrast` |
| Overlay | `rgba(5,7,11,0.72)` | `--overlay` |

**Color Notes:** Orange accent on stepped dark surfaces. In dark mode fill and
text tones are identical (vivid hues clear 6:1 on dark); they diverge only in
light mode.

### Color Palette — light (`html[data-theme="light"]`)

| Role | Value | CSS Variable |
|------|-------|--------------|
| Background / elevated | `#eef1f6` / `#ffffff` | `--bg` / `--bg-elevated` |
| Surface 1 / 2 / 3 | `#ffffff` / `#f3f6fb` / `#e7ecf4` | `--surface-1/2/3` |
| Border / strong | `#d7dde7` / `#b9c2cf` | `--border` / `--border-strong` |
| Text primary / secondary / muted | `#1b2230` / `#5b6675` / `#5f6875` | `--text-*` |
| Accent fill / hover / text | `#e86a0c` / `#d15f08` / `#b04f07` | `--accent` / `--accent-hover` / `--accent-text` |
| Success fill / text | `#0e9f85` / `#0a7561` | `--success` / `--success-text` |
| Warning fill / text | `#e08a00` / `#8a5200` | `--warning` / `--warning-text` |
| Danger fill / text | `#dc2626` / `#c0392b` | `--danger` / `--danger-text` |
| Info fill / text | `#0891b2` / blue (value in tokens.css) | `--info` / `--info-text` |
| Ink on accent fill | `#15110a` (white fails at 3.2:1) | `--accent-contrast` |
| Ink on success/danger fill | `#ffffff` (deep fills flip back to white) | `--success-contrast` / `--danger-contrast` |

### Status Rules (semantic mapping — later tasks obey this)

- **ok → `--success`**, **warn/expiring → `--warning`**, **error/down → `--danger`**, **neutral info → `--info`**. The three primary states must stay visually distinct in BOTH themes.
- Fill vs text split: use the plain token (`--success`, `--danger`…) only for dots, bars, chart series, borders; use `--*-text` for label text and pill text; use `--*-soft` for pill/chip backgrounds.
- Legacy hue aliases (`--orange`, `--green`, `--red`, `--cyan`, `--success-color`…) resolve to the **text** tones — labels only, never fills.
- Filled status buttons take the contrast ink (`--danger-contrast`, `--success-contrast`), never plain white/black.
- Light mode: always re-check contrast of the `-text` tones; the vivid fills fail AA as text there.

### Typography

- **Body Font:** Manrope — `--font-family: 'Manrope', ui-sans-serif, system-ui, …`
- **Display Font:** Space Grotesk — `--font-display: 'Space Grotesk', 'Manrope', …`
- **Loading:** self-hosted woff2 under `/fonts/` via `<link rel="stylesheet" href="/fonts/fonts.css">` in `index.html`. No Google Fonts CDN.
- **Usage:** body, nav links, buttons, form labels use `--font-family`; modal/notification headings and stat numbers use `--font-display`.
- **Mood:** technical, compact, numeric-friendly, high legibility at 11–15px.

**Type scale:**

| Token | Value | Token | Value |
|-------|-------|-------|-------|
| `--font-size-2xs` | 10px | `--font-size-xl` | 22px |
| `--font-size-xs` | 11.5px | `--font-size-2xl` | 28px |
| `--font-size-sm` | 13px | `--font-size-3xl` | 34px |
| `--font-size-md` | 15px | `--line-height-tight/snug/normal` | 1.2 / 1.35 / 1.55 |
| `--font-size-lg` | 18px | `--font-weight-*` | 400 / 500 / 600 / 700 / 800 |

Tracking: `--tracking-tight: -0.01em`, `--tracking-wide: 0.04em`, `--tracking-caps: 0.1em`.

**RTL:** no physical left/right in component CSS — logical properties only
(`margin-inline`, `inset-inline-start`, `text-align: start`). fa locale: append
Vazirmatn (or system Naskh) to the font stacks before the generic fallback.

### Spacing Variables

*Density: 8/10 — Dense / Dashboard. 4px base grid.*

| Token | Value | Token | Value |
|-------|-------|-------|-------|
| `--space-1` | 4px | `--space-6` | 24px |
| `--space-2` | 8px | `--space-7` | 32px |
| `--space-3` | 12px | `--space-8` | 40px |
| `--space-4` | 16px | `--space-9` | 48px |
| `--space-5` | 20px | `--space-10` | 64px |

**Radii:** `--radius-xs` 4px · `--radius-sm` 6px · `--radius-md` 10px · `--radius-lg` 14px · `--radius-xl` 20px · `--radius-pill` 999px.

**Control heights:** `--control-h-sm` 30px · `--control-h-md` 38px · `--control-h-lg` 44px · `--row-h` 34px (dense table/list rows).
Icon-only buttons must resolve to ≥44px hit area — use `--control-h-lg` or padding.

**Layout metrics:** `--topbar-h: 64px` · `--sidebar-width: 220px` · `--sidebar-collapsed-width: 72px` · `--content-max: 1480px`.

**Breakpoints (written literally at call sites):** phone `max-width: 767.98px`
(must match DashboardLayout `innerWidth < 768` exactly — no 760/768 drift) ·
tablet `< 900px` off-canvas sidebar · desktop `≥ 900px` persistent rail.

### Shadows, Focus, Motion

| Level | Dark value | Usage |
|-------|-----------|-------|
| `--shadow-xs` | `0 1px 2px rgba(0,0,0,0.35)` | Rows, controls |
| `--shadow-sm` | `0 2px 8px rgba(0,0,0,0.4)` | Chips, popovers-lite |
| `--shadow` | `0 4px 14px rgba(0,0,0,0.5)` | Cards, buttons |
| `--shadow-lg` | `0 16px 48px rgba(0,0,0,0.7)` | Modals, drawers, dropdowns |

Light values are repainted in the light block (`0.06 / 0.08 / 0.12` alpha).

- **Focus:** `--focus-ring: var(--accent)` — 3px halo `--focus-ring-shadow: 0 0 0 3px var(--accent-soft)` with `--focus-ring-offset: 2px`. Visible on every interactive element.
- **Transitions:** `--transition-fast: 0.15s ease` · `--transition-normal: 0.25s ease` · `--transition-slow: 0.4s ease`; curves `--ease-standard`, `--ease-out`.
- **Z-scale (bottom → top):** nav 70 · mobile-nav 95 · topbar 110 · mobile-overlay 118 · mobile-drawer 119 · hamburger 120 · drawer 130 · modal 200 · popover 300 · toast 400 · progress 500 · command 600 · popover-high 700. Floaters declare a z token, never a raw number.

---

## Component Specs

### Buttons

```css
/* Primary button — accent fill, near-black ink */
.btn-primary {
  background: var(--accent);
  color: var(--accent-contrast);
  min-height: var(--control-h-md);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-sm);
  font-weight: 600;
  transition: background var(--transition-fast), filter var(--transition-fast);
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-primary:focus-visible { box-shadow: var(--focus-ring-shadow); outline: none; }

/* Secondary button — surface fill, steps up on hover */
.btn-secondary {
  background: var(--surface-2);
  color: var(--text-primary);
  border: 1px solid var(--border);
}
.btn-secondary:hover { background: var(--surface-3); }

/* Destructive — danger fill + contrast ink */
.btn-danger {
  background: var(--danger);
  color: var(--danger-contrast);
  border: 1px solid var(--danger);
}
```

### Cards / Panels

```css
.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  box-shadow: var(--shadow);
  transition: background var(--transition-normal), box-shadow var(--transition-normal);
}
.card:hover { background: var(--surface-2); }
```

### Inputs

```css
.input {
  background: var(--input-bg);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  min-height: var(--control-h-md);
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-md);
  transition: border-color var(--transition-fast);
}
.input:focus-visible {
  border-color: var(--accent);
  outline: none;
  box-shadow: var(--focus-ring-shadow);
}
```

### Modals

```css
.modal-overlay { background: var(--overlay); }
.modal {
  background: var(--surface-1);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  box-shadow: var(--shadow-lg);
  max-width: 500px;
  width: 90%;
}
.modal-header h2 { font-family: var(--font-display); }
```

### Status Pill

```css
.status-pill {
  background: var(--success-soft);   /* --*-soft per state */
  color: var(--success-text);        /* text tone, never the fill */
  border-radius: var(--radius-pill);
  font-size: var(--font-size-xs);
}
```

---

## Style Guidelines

**Style:** Dark ops console — functional, dense, high-contrast, token-driven

**Keywords:** console, dark surfaces, stepped elevation, orange accent, compact tables, numeric, sans-serif, grid-based, semantic status

**Best For:** Internal admin tools, monitoring dashboards, ops consoles, data-dense tables

**Key Effects:** 150–250ms transitions, accent focus halos, soft status washes, quiet borders, no decorative motion

### Page Pattern

**Pattern Name:** Hero + Features + CTA (legacy generated reference)

> For the admin console this pattern applies only as structural reference —
> no hero/CTA marketing sections. Reuse token and type rules only.

- **Conversion Strategy:** Deep CTA placement. For CTA label text, verify at least 4.5:1 against the button fill; use 7:1 only when the product explicitly targets AAA normal-text contrast. Keep focus and component boundaries independently visible. Disable hero parallax under reduced motion and render its static final state.
- **CTA Placement:** Hero (sticky) + Bottom
- **Section Order:** Hero with headline/image > Value prop > Key features (3-5) > CTA section > Footer

---

## Motion

**Scroll Reveal** (Subtle) — Trigger: scroll (viewport enter) | Duration: 300-400ms | Easing: `power1.out`

```js
gsap.from(el, { opacity: 0, y: 12, duration: 0.35, ease: 'power1.out', scrollTrigger: { trigger: el, start: 'top 90%', toggleActions: 'play none none reverse' } });
```

**Framework notes:** Requires the ScrollTrigger plugin registered once via gsap.registerPlugin(ScrollTrigger); Use matchMedia('(prefers-reduced-motion: reduce)') to skip non-essential motion and render the final state immediately

- ✅ Keep the y offset small (8-16px) so it reads as a fade, not a slide
- ❌ Don't reveal below-the-fold content needed for SEO/crawlers as invisible-by-default without a no-JS fallback
- ⚡ toggleActions 'play none none reverse' avoids re-triggering on every scroll direction change

---

## Anti-Patterns (Do NOT Use)


### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y
- ❌ **Hard-coded hex values in component CSS** — Use `var(--…)` tokens from `tokens.css`; the file owns every `:root` declaration
- ❌ **White/black ink on status or accent fills by default** — use the `--*-contrast` tokens
- ❌ **Physical left/right properties** — logical props only (RTL)

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Text contrast 4.5:1 minimum in BOTH themes (status text uses `--*-text`)
- [ ] Focus states visible for keyboard navigation (accent ring)
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px; tables scroll inside a container at 375px
- [ ] Touch targets ≥44px on icon buttons
- [ ] No content hidden behind fixed topbar (64px) / bottom nav
- [ ] No horizontal scroll on mobile
- [ ] New user-visible copy: en key + `t()` present
- [ ] No raw hex in component CSS — tokens only
