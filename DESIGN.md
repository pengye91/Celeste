# Celeste Mission Control — Design System

**Project:** Celeste-DAG Monitoring UI (CMC)  
**Date:** 2026-06-12  
**Branch:** `celeste-verification-examples`

---

## 1. Design Principles

1. **The sky is the interface.** Workflows are celestial objects. The operator is an astronomer at a console. Every screen reinforces this metaphor through color, motion, and spatial memory.
2. **Authority over decoration.** Information density is controlled, not maximal. Every pixel shows state, enables action, or creates spatial memory.
3. **Empty states are features.** "No items found" is not acceptable. Every empty state explains why the sky is empty and offers a primary action.
4. **Status is never color-only.** Every status signal pairs color with an icon and a text label.
5. **Motion improves hierarchy.** Ambient motion creates atmosphere; interactive motion confirms action; both respect `prefers-reduced-motion`.
6. **Subtraction default.** If an element does not earn its pixels, remove it. Avoid generic dashboard mosaics.
7. **Desktop-first, intentional everywhere.** CMC is built for operators on large screens, but every smaller viewport has a specified behavior.

---

## 2. Anti-Patterns (Forbidden)

The following read as generic AI-generated SaaS and are not allowed:

1. Purple/violet/indigo gradients or blue-to-purple schemes.
2. Symmetric 3-column feature grids with icon + title + description.
3. Icons inside colored circles as decoration.
4. Centered everything (`text-align: center` on headings and cards).
5. Uniform bubbly border-radius on every element.
6. Decorative blobs, floating circles, wavy SVG dividers.
7. Emoji as design elements.
8. Colored left-border on cards as status.
9. Generic hero copy ("Welcome to CMC", "Unlock the power of...").
10. Cookie-cutter page rhythm (hero → features → testimonials → pricing → CTA).

---

## 3. Color System

### Primitives

```css
:root {
  --space-950: #050814;
  --space-900: #0a0f1c;
  --space-800: #11172b;
  --space-700: #1a1f3d;
  --space-600: #2a3159;
  --space-500: #4a547a;
  --space-400: #7b86a9;
  --space-300: #a9b3cc;
  --space-200: #d4dceb;
  --space-100: #f1f4fb;

  --aurora-500: #00f0ff;
  --aurora-400: #4ff7ff;
  --aurora-300: #8afbff;
  --aurora-900: #002b2e;

  --solar-500: #ff9f43;
  --solar-400: #ffb978;
  --solar-900: #3d220a;

  --mars-500: #ff4757;
  --mars-400: #ff7a85;
  --mars-900: #3d0a0f;

  --nebula-500: #2ed573;
  --nebula-400: #6de69d;
  --nebula-900: #0a3d20;

  --comet-500: #a55eea;
  --comet-400: #c49af5;
  --comet-900: #2a153d;
}
```

### Semantic Roles

```css
:root {
  --bg-root: var(--space-950);
  --bg-panel: rgba(10, 15, 28, 0.72);
  --bg-panel-solid: var(--space-900);
  --bg-inset: var(--space-800);
  --border-subtle: rgba(119, 132, 168, 0.18);
  --border-glow: rgba(0, 240, 255, 0.25);
  --text-primary: var(--space-100);
  --text-secondary: var(--space-300);
  --text-tertiary: var(--space-400);
  --status-running: var(--aurora-500);
  --status-completed: var(--nebula-500);
  --status-failed: var(--mars-500);
  --status-paused: var(--solar-500);
  --status-pending: var(--space-500);
  --status-cancelled: var(--space-400);
}
```

### Atmosphere

- Subtle animated film grain overlay (`mix-blend-mode: overlay`, opacity `0.04`).
- Slow radial aurora gradient behind the main canvas.
- Thin horizon line / crosshair at 1/3 height on dashboard pages.

---

## 4. Typography

| Role | Font | Weight | Size / Line | Usage |
|------|------|--------|-------------|-------|
| Display / page titles | Bodoni Moda | 400 | 48/52 | Dashboard title, workflow name |
| Section headers | Bodoni Moda | 400 | 32/36 | Page section headings |
| Card titles | Syne | 600 | 24/28 | Panel titles, KPI labels |
| Emphasis labels | Syne | 500 | 18/24 | Form labels, nav tooltips |
| Body | Syne | 400 | 15/22 | Descriptions, table text |
| Metadata | Syne | 400 | 13/18 +0.02em | Timestamps, secondary labels |
| Monospace / code | JetBrains Mono | 400 | 11/14 | Timestamps, badges, JSON |

Fallback stacks:
- `Bodoni Moda, Georgia, serif`
- `Syne, system-ui, sans-serif`
- `JetBrains Mono, Menlo, monospace`

---

## 5. Spacing & Layout

- Base grid unit: `4px`.
- Panels use `16px` internal padding on desktop, `12px` on mobile.
- Section gaps: `24px` desktop, `16px` mobile.
- Page canvas padding: `32px` desktop, `16px` mobile.
- Sidebar rail width: `56px` (icon-only), expands to `160px` on hover.
- Bottom bar height: `56px` (mobile/tablet).
- Top bar height: `56px`.

---

## 6. Components

### 6.1 Status Orb

- A small circle (12 px desktop, 16 px touch) using the semantic status color.
- Running status: double-ring pulse animation (CSS box-shadow).
- Always paired with a text label and an icon.

### 6.2 Panel

- Background: `--bg-panel` with `backdrop-filter: blur(12px)` where supported; falls back to `--bg-panel-solid`.
- Border: `1px solid var(--border-subtle)`.
- Border-radius: `4px` (sharp, console-like; never bubbly).
- Hover: subtle lift `translateY(-2px)` + `--border-glow`.

### 6.3 Button

- Primary: filled `--aurora-500` text on `--space-900` background.
- Secondary: outlined with `--border-subtle`.
- Danger: filled `--mars-500`.
- Touch target: minimum `44 × 44 px`.

### 6.4 Input

- Background: `--bg-inset`.
- Border: `1px solid var(--border-subtle)`.
- Focus: `2px` `--aurora-500` ring, `2px` offset.

### 6.5 Table

- Row height: `48 px`.
- Header: `--text-secondary`, uppercase, `xs` size, `+0.04em` tracking.
- Hover row: `--bg-inset`.
- Status column: orb + label.

### 6.6 Card (Workflow Card)

- Asymmetric composition: progress arc on one side, metadata cluster on the other.
- No uniform large radius; use `4px`.
- No colored left border for status; use orb + label.

---

## 7. Motion

### Ambient

- Grain overlay: `steps()` noise animation at 12 fps, opacity `0.04`.
- Aurora gradient: slow `background-position` drift over 60 s.
- Running status orbs: double-ring echo pulse.
- Constellation edges: particles drift along active dependency edges.

### Interactive

- Page transitions: `layoutId` shared-element where appropriate.
- Card hover: `translateY(-2px)` + border glow.
- Sidebar: icons slide, labels fade on hover.
- Toasts: slide in from top-right.

### Reduced Motion

When `prefers-reduced-motion: reduce`:
- Disable grain, aurora drift, pulses, autopan.
- Use instant transitions.
- Preserve state changes without animation.

---

## 8. Accessibility

- Dark mode only.
- Minimum contrast: body `4.5:1`, large text/UI `3:1`.
- Focus rings: `--aurora-500`, `2px`, `2px` offset.
- Touch targets: `44 × 44 px` minimum; bottom bar `48 × 48 px`.
- Keyboard: full navigation through rail, tables, DAG nodes; `Esc` closes panels.
- Screen readers: ARIA landmarks, `aria-live` for status changes, DAG nodes announce role/status/label.

---

## 9. Responsive Breakpoints

| Viewport | Range | Key behavior |
|----------|-------|--------------|
| Desktop | ≥1280 px | Full side rail, multi-column dashboard, canvas + side panel |
| Tablet | 768–1279 px | Bottom icon bar, 2-column cards, scrollable tables, bottom-sheet inspector |
| Mobile | <768 px | Single column, bottom bar, constellation as simplified node list, full-screen sheets |
| Ultrawide | ≥1920 px | Extra context column, larger canvas |

---

## 10. Iconography

- Use **Lucide React** exclusively.
- No emoji.
- Icons are monochrome (`--text-secondary` or `--text-primary`) unless part of a status orb.

---

## 11. Voice & Copy

- Utility language, not marketing copy.
- Headings state what the area is or what the operator can do.
- Empty states explain why and offer an action.
- Error states are one-line operator messages, never raw exceptions.

---

## 12. Status Language

| Status | Color | Icon | Use |
|--------|-------|------|-----|
| Running | `--aurora-500` | Loader / activity | Currently executing |
| Completed | `--nebula-500` | Check circle | Finished successfully |
| Failed | `--mars-500` | Alert octagon | Finished with error |
| Paused | `--solar-500` | Pause circle | Awaiting human input |
| Pending | `--space-500` | Clock | Queued or waiting |
| Cancelled | `--space-400` | X circle | Aborted |

---

*Generated from `/plan-design-review` on 2026-06-12. Update this file as the design vocabulary evolves.*
