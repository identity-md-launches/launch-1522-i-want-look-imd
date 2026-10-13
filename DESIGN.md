# IMD ChadBoard design system

## Overview

ChadBoard is a query tool for visitors exploring the on-chain participation of
activated IMD seats. Its visual idea is a restrained field report: an ink-colored
wordmark and ranking bars, a paper-colored background, and one violet primary
action. The data/query surface comes before the explanation. No live statistics
or rankings are illustrated with fabricated examples.

The implementation is React with plain CSS. `web/src/styles.css` is the source of
truth for tokens and responsive behavior; `web/src/App.tsx` contains the page and
payment flows, and `web/src/Results.tsx` contains the report components. There is
one light theme and one English page with anchor navigation.

## Colors

Primitives and semantic aliases are defined together at the top of
`web/src/styles.css`. Components consume semantic tokens. Hex notation is
consistent across the implementation; no gradients or translucent text are used.

| Semantic token | Primitive / exact value | Use |
| --- | --- | --- |
| `--color-page` | `--neutral-50`, `#f6f5f1` | Page background |
| `--color-surface` | `--neutral-0`, `#ffffff` | Query surface, inputs, dialogs, results |
| `--color-subtle` | `--neutral-100`, `#eeede8` | Neutral hover/selection and close button |
| `--color-border` | `--neutral-200`, `#d8d6d0` | Structural separators and panel borders |
| `--color-control-border` | `--neutral-500`, `#706c78` | Input and secondary-button boundaries |
| `--color-text` | `--neutral-900`, `#272438` | Primary text, brand and diagram bars |
| `--color-muted` | `--neutral-600`, `#625e69` | Supporting text and data labels |
| `--color-accent` | `--violet-700`, `#6543b3` | Primary action background |
| `--color-accent-hover` | `--violet-800`, `#51328f` | Primary hover and links |
| `--color-guide` | `--violet-100`, `#e8e0f5` | Desktop scoring explanation |
| `--color-illustration` | `--violet-300`, `#c8b9f9` | Decorative brand/share-card bars |
| `--color-on-accent` | `--neutral-0`, `#ffffff` | Primary-button text |
| `--color-focus` | `--violet-800`, `#51328f` | 3px keyboard focus outline |
| `--color-warning-bg` | `--amber-100`, `#fff3d8` | No-wallet callout |
| `--color-warning` | `--amber-800`, `#795419` | Waiting-state dot and warning text |
| `--color-error` | `--red-800`, `#a02c35` | Field and transaction errors |
| `--color-success` | `--green-700`, `#286044` | Current-snapshot indicator |

The dialog backdrop is `rgb(25 21 40 / .55)`; no text is placed on it. Status
colors always have adjacent words. Decorative lavender bars do not encode a live
rating. Rendered text contrast passed the pinned probe; measured pairs and
coverage are recorded in `docs/WEBSITE-VALIDATION.md`.

## Typography

The UI uses the system stack `Arial, Helvetica, sans-serif`, at weights **400** and
**700**. There are no font downloads. Addresses and transaction/evidence hashes
use `'Courier New', Courier, monospace`, preserving the complete value with
`overflow-wrap: anywhere`; prose never uses monospace.

| Token | Default size | Role |
| --- | ---: | --- |
| `--text-sm` | 0.875rem / 14px | Labels, hints, metadata, addresses |
| `--text-base` | 1rem / 16px | Body, inputs, buttons |
| `--text-md` | 1.25rem / 20px | Panel title, metric values, wordmark |
| `--text-lg` | 1.75rem / 28px | Section titles and query fee |
| `--text-xl` | 2.25rem / 36px | Guide title and narrow-screen page title |
| `--text-display` | 3rem / 48px | Desktop page title |

Body line height is 1.5; headings use 1.15 and buttons 1.4. The main heading uses
−0.045em tracking; section headings use −0.03em and the guide heading −0.035em.
Small content has natural spacing and sentence case. Headings use balanced
wrapping. Supporting descriptions use `text-wrap: pretty`, with natural wrapping
as the fallback. Numbers are tabular. Longer explanatory paragraphs are limited
to 68ch; the availability message is limited to 82ch.

All editable text controls are 16px at the default root size to avoid iOS input
zoom. Root font enlargement is allowed. The six-size scale remains intact across
breakpoints; the responsive hierarchy selects smaller existing tokens.

## Layout

The shared `.wrap` is at most 1160px wide with 40px side gutters on wide screens.
Spacing tokens cover 4, 8, 12, 16, 24, 32, 40 and 48px. Section transitions use up
to 64px. Labels and their inputs are tightly grouped; separate tasks get at least
16–24px. `.workspace` is a two-column `1.25fr / 1fr` grid with a 24px gap, placing
the query on the left and static scoring weights on the right.

The implemented breakpoints are:

- **65rem / 1040px:** stack the page heading and network label, reduce panel
  padding to 24px, reduce the main heading to 36px, and stack result heading actions.
- **48rem / 768px:** use one query column and 20px page gutters. Hide only the
  redundant scoring illustration; the scoring method remains in the help below.
  Hide the header help link while retaining in-page help, stack the method section,
  use two columns for snapshot metrics, and wrap the footer.
- **30rem / 480px:** use 16px page gutters and 20px query-panel padding. Keep
  header text and wallet control at readable sizes, hide the decorative wallet
  icon, and allow the header to wrap with enlarged text. Use a compact results
  grid (36px rank / flexible wallet / 60px score). Wallet details span the full row.

The query-type buttons wrap rather than overflow when text is enlarged. Fixed
heights are not applied to text containers. Textarea height can be resized; long
addresses wrap, never ellipsize. Report lists render 25 rows per page. Token
accounting becomes one label/value per row on narrow screens. Dialogs are at most
560px wide and `100dvh − 32px` high, scrolling internally when needed.

Production-rendered checks covered 320, 390, 820 and 1440px in Chromium and
WebKit. At 390×844 the product, wallet field, fee and “Check query” button are on
the first screen. 200% root text enlargement was also checked; it is not claimed
to be a native browser zoom test. See validation for limits.

## Elevation & Depth

The system is deliberately flat. Query/results panels use a single 1px structural
border and no shadow. The scoring guide uses a tonal background without a border.
Dialogs use a darker backdrop and the browser's top layer, without card shadows.
There is no sticky or fixed chrome covering the main content. A skip link becomes
visible above the page when focused.

## Shapes

`--radius-control` is 8px; `--radius-panel` is 16px. Inputs, primary/secondary
buttons and selectable leaderboard options use the control radius. Query panels,
results and dialogs use the panel radius. The wordmark is a 40px SVG (32px on
small phones); its decorative ranking bars and favicon use the same geometry.
Indicators are small circles with adjacent status text. Decorative SVGs are
hidden from assistive technology.

## Components

| Component or pattern | Source | Behavior and reuse |
| --- | --- | --- |
| `Mark`, `Icon` | `web/src/App.tsx` | Local SVG brand and four 20px outline icons; icons inherit text color and have no separate click targets |
| `.button` | `web/src/styles.css` | Primary violet, bordered secondary and wallet variants; 48px minimum height, 44px for narrow header control; clear disabled state |
| `.mode-switch` | `web/src/App.tsx` | Two native buttons with `aria-pressed` and a selected underline; native keyboard activation; not a custom ARIA tab widget |
| `.wallet-input` | `web/src/App.tsx` | Visible textarea label, adjacent format hint, focus on validation error, `aria-invalid`/described error; no input modification while checking |
| `.pack-option` | `web/src/App.tsx` | Native radios inside full clickable labels; selected border/background; arrow-key selection |
| `SnapshotStatus` | `web/src/App.tsx` | Loading/current/empty/stale/unreachable state plus refresh; words accompany dots; unknown values never become invented zero counts |
| `Dialog` | `web/src/App.tsx` | Native modal dialog and close button; Escape closes unless wallet signing is active; explicit restoration of focus to the opener |
| `.review-details`, `.consent` | `web/src/App.tsx` | Matched count, epoch, exact fee, full recipient, paying account and checkbox before an irreversible transfer |
| `.payment-status` | `web/src/App.tsx` | Persistent pending reference, repeat receipt check, downloadable/restorable recovery JSON, replacement hash and explicit discard confirmation |
| `Results`, `WalletDetail` | `web/src/Results.tsx` | Complete wallet addresses, rank, score, tier, metric/token disclosures, filter, 25-row pagination, export and provenance |
| `.explainers` | `web/src/App.tsx` | Native `details`/`summary` for scoring, trust, fee policy, missing wallets and recovery; no custom accordion keyboard model |

Dynamic query and payment updates use polite status regions; inline urgent errors
use alerts. Confirmation/rejection never automatically submits a second transfer.
The only interaction animation is a 120ms named-property button transition with
0.96 press scale, enabled only under `prefers-reduced-motion: no-preference`.
There is no animated page entrance, infinite motion or `transition: all`. Focus
uses a 3px offset outline; forced-colors mode uses the system Highlight color.

## Do's and Don'ts

- Start another surface with `.wrap`, an existing heading size and the spacing tokens.
- Give one consequential action the filled primary style; use secondary buttons
  for downloads, account management and navigation.
- Preserve complete addresses, exact amounts, observation time and trust context.
- Keep input errors beside their controls and make recovery actions explicit.
- Add any necessary new color by semantic role; do not reuse the border color as text.
- Reuse native form/disclosure/dialog semantics. Recheck focus return when changing dialogs.
- Do not add sample wallets, made-up statistics, marketing sections, extra fonts,
  nested decorative cards or motion to fill an empty data state.
- Keep all runtime art local. The editable share-card source is
  `web/assets/share.svg`; the delivered raster is `web/public/share.png` (1200×630).

Guidance attribution: Better Interface by Jakub Krehel, MIT, pinned commit
`267330e1adfc66a718fb65fa6918c1f06d0a689e`; documentation method adapted from Paul
Bakaus's Impeccable, Apache-2.0, commit
`9d715cc4f5564a990ca8345abfdd5df6dc9b41c8`. See `docs/DESIGN-LICENSES.txt` for the
preserved license texts. These are design references, not frontend dependencies.
