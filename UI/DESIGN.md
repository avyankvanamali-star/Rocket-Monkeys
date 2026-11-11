# Shadow Self UI: design system

A mission-health workspace for the crew medical officer. A deep-navy frame (sidebar and a compact header) holds the only decoration: a sparse static star field and one fine orbital line. Inside it sits a cool-gray work surface of opaque white tiles, laid out like an instrument wall. Each tile has a small caption, a short title, one large tabular number and a comparison line.

The tokens are locked: change them in the `:root` block of `static/shadow.css` and nowhere else.

## The task the layout follows

1. Choose a crew member (sidebar).
2. Choose a mission day (header).
3. Understand the status (Overview: summary, system profile, needs attention).
4. Inspect a change (select a system, then see its trend, measurements and tolerance band).
5. Review the evidence and the existing action (details drawer, Systems, Report).

Overview answers four questions without scrolling at 1440 × 900: what is happening, what changed, what needs attention, and where to inspect it. It has three regions (summary, radar, priority), the five-system strip, and the start of the linked trend.

## What each reference contributed

- **Dashboard tiles (primary):** dense tile grid with 12px seams; caption, title, big number and comparison line ("▼ 31 vs day 2 (34)"); right-aligned tabular figures; hairline table rows.
- **Radar:** concentric pentagon grid, faint spokes, scale numbers along one gap, labels outside the vertices, one translucent filled shape. It uses our five real systems on the shared 0–100 score.
- **Space:** stars and a single orbit, only in the navy frame. They are never behind data or body text, have pointer events off, and never move.

## Colour

| Token | Hex | Use |
|---|---|---|
| `--frame` | `#101827` | Sidebar and header (deep navy) |
| `--bg` | `#E8EDF4` | Workspace |
| `--panel` | `#FFFFFF` | Tiles, drawer |
| `--sunken` | `#F3F6FA` | Secondary surfaces, table heads, activity rows |
| `--text` | `#142033` | Main text (16.4:1 on white) |
| `--dim` | `#526176` | Secondary text (6.3:1) |
| `--faint` | `#5E6B80` | Captions, axes (5.4:1 on white, 4.6:1 on the workspace) |
| `--accent` | `#3459E6` | The only accent: primary action, selection, focus, the current-day line |

**Status:**

| Status | Fill (graphics) | Text shade | Icon |
|---|---|---|---|
| Nominal | `#1F8A5B` | `#17704A` | check circle |
| Watch | `#C27C0E` | `#8A5700` | ! circle |
| Act | `#D9541E` | `#B0420F` | ! triangle |
| Urgent | `#C8312F` | `#B3261E` | ! octagon |
| No data | `#8D99AA` | `#5E6B80` | dash circle |

A status is never shown by colour alone: it always has an icon and a word. Navigation selection is shown in blue or white, never in a status colour. In the frame, status dots use lighter tints of the same hues.

Colour means status, never series. Chart lines are neutral gray; a selected system is blue; Overall is ink. Points take their status colour.

Not allowed: glass or blur, glows, gradients on cards, HUD decoration, moving or particle backgrounds, purple.

## Tolerances (from the engine, not the design)

- **Score zones:** the Watch zone is under 75 and the Act zone is under 50 (actions/act.py). These are drawn on the radar, the summary meter and every score chart.
- **Measurement band:** pre-flight baseline ± MDC (the measurement noise). It is drawn behind each measurement's history.
- **Scale honesty:** scores share one 0–100 scale where higher means closer to the usual self. Missing values stay missing: no zero and no line drawn through a gap. The previous-day shape is labelled "Day N", never "baseline".

## Type

- **Faces:** Geist for everything, with tabular numerals for metrics. Geist Mono only for timestamps, units, file names and the log.
- **Scale:** 11 / 12 / 13 / 14 (body) / 15 (tile titles) / 18 / 24 / 28 / 44 (the Shadow Score).
- **Case:** sentence case everywhere. There are no eyebrows and no uppercase tracked labels.

## Spacing, shape, surfaces

- **Spacing:** a 4px grid (`--s1` 4 to `--s10` 40). Tiles are 12px apart, with 16 × 20px padding.
- **Radius:** 4 (tags), 6 (controls), 8 (rows, menus), 10 (tiles).
- **Control sizes:** 28 (small), 34 (buttons), 38 (inputs).
- **Surfaces:** tiles are opaque white with a 1px `--line` border and a 1px offset shadow. Floating things (tooltips, drawer, busy card) use `--shadow-2`.
- **Sidebar:** 232px, collapsible to 68px (remembered per browser). Below 900px it becomes a drawer opened from the header.

## Components and states

- **Selection:** one shared state. A radar label, a system tile, a flagged-measurement row or a Systems "Quick view" all select a system. Selection updates the radar (others fade to 40–60%), the strip (blue ring), the priority list (alerts filtered, other activities dimmed, "Show all"), the trend, and the details button. Selecting the same label or tile again, or "Show all systems", clears it.
- **Details drawer:** a modal dialog from the right. It has the score, status and change, the engine's explanation, the score trend, every measurement (value, unit, baseline, change, MDC, Shadow expected, status, reason), the alerts and the planned actions. Escape and the backdrop close it, and focus returns to the opener.
- **Day and crew changes:** the page is fetched and swapped in place, keeping the tab and the selection. History works, and ← → step through days. If the fetch fails, the browser loads the page normally.
- **Data:** the value is validated against the metric's accepted range next to the field before it is sent. Upload results appear inside the box that sent them. Destructive actions sit in a separate Reset tile and ask first.
- **Engine:** last run, result (completed or failed), counts and errors come before the log. The log is collapsible and filterable. Runs disable every button until they finish, so a run can't be started twice.

## Motion

- **Easing:** strong ease-out `cubic-bezier(.23, 1, .32, 1)` for responses. `cubic-bezier(.77, 0, .175, 1)` only for the sidebar indicator moving between tabs.
- **Durations:**
  - 140ms for control feedback (hover, press to 97%).
  - 200ms for selection (fades, rings).
  - 240ms in and 160ms out for the drawer.
  - 320ms for the radar moving between two real days. The in-between frames are a transition, not data.
- **Small touches:** tooltips follow the pointer with a 90ms transform. Revealed alert rows rise 4px with a 25ms stagger. The trend panel crossfades (200ms) when the selection changes.
- **Never:** count-ups, a score ring drawing in, replayed entrances, card tilt or bounce, moving stars.
- **Reduced motion:** every duration drops to effectively zero, so state changes happen instantly.
