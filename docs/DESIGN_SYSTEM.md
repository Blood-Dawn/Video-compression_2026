# SVCS design system notes

Companion to `docs/REDESIGN.md`. This file records the tokens and the reusable components that the dashboard (`src/gui/templates/index.html`) and the Android app (`mobile/android/.../ui`) share, so a change made in one place can be mirrored in the other.

## Token parity

The values below are the dark theme, and they are the same on both platforms. Light values are in the Light theme section. The dashboard names are CSS variables in the `:root` block of `index.html`. The Android names are vals in `ui/theme/Color.kt`.

| Role | Dashboard | Android | Value |
| --- | --- | --- | --- |
| Page background | `--bg` | `SvcsBg` | #0a0e14 |
| Card surface | `--surface` | `SvcsSurface` | #10192a |
| Raised surface | `--surface2` | `SvcsSurface2` | #162238 |
| Highest surface | `--surface3` | `SvcsSurface3` | #1e3a52 |
| Decorative border | `--border` | `SvcsBorder` | #2a4466 |
| Bright border | `--border-bright` | `SvcsBorderBright` | #3a5a7a |
| Control border (inputs, buttons) | `--border-ctl` | `SvcsBorderCtl` | #5d7da3 |
| Primary accent | `--amber` | `SvcsAmber` | #ffb900 |
| Dim accent | `--amber-dim` | `SvcsAmberDim` | #8a6300 |
| Dim accent that is readable as text | `--amber-text` | `SvcsAmberText` | #d99a00 |
| Success | `--green` | `SvcsGreen` | #2dd6a0 |
| Info and live | `--teal` | `SvcsTeal` | #1fd4c8 |
| Error | `--red` | `SvcsRed` | #ff5555 |
| Body text | `--text` | `SvcsText` | #d8e8f5 |
| Secondary text | `--text-dim` | `SvcsTextDim` | #95a9c0 |
| Headline text | `--text-bright` | `SvcsTextBright` | #f0f8ff |

Contrast rules these values were chosen for: body text 4.5:1 or better on every surface, control borders 3:1 or better against their background, dim amber text 7.9:1.

Differences to know about. Android has `SvcsOrange` (warnings such as "it may barely shrink") and `SvcsBlue`, which the dashboard does not define. The dashboard has alias variables (`--surface1`, `--bg-secondary`, `--bg-tertiary`, `--text-primary`) that exist only because older code referenced them. Do not add new aliases. Typefaces are Bebas Neue (display), Space Mono (labels and numbers) and Outfit (body) on both platforms. Sizes: nothing under 12px on the dashboard, text in sp on Android so it scales with the user's font setting.

When you change a color, change it in both files in the same commit, and update the contrast note beside it.

## Spacing and type scale

New code uses a 4, 8, 16, 24 spacing scale (dp on Android, px on the dashboard). Older inline styles that use other values are being moved over as the files are touched, not in one sweep. Touch targets are 44px on the dashboard and 48dp on Android. Focus ring on the dashboard is 3px amber with a 2px offset.

## Components

Each entry lists where it lives, its states, and what it must expose to assistive technology.

### Button

Dashboard: `.btn` with `.btn-primary`, `.btn-ghost`, `.btn-danger`, `.btn-browse`. Android: `SvcsPrimaryButton`, `SvcsSecondaryButton` (with `danger = true`). One amber primary button per screen. Secondary buttons are outlined with the control border. Destructive buttons are red outline. States: default, hover or pressed, focus (visible ring), disabled (dimmed and not clickable), and on the dashboard Start also has a locked state until Setup is complete. Accessibility: real button element or `Role.Button`, a text label (icon-only buttons need a name), 44px or 48dp minimum.

### Input

Dashboard: `input`, `select`, `textarea` with a visible `<label for>`. Android: `OutlinedTextField` with a label. States: default, focus, filled, invalid (`:user-invalid` styling plus `aria-invalid` once the user has touched the field), disabled while a job runs. The control border token is used so the field edge is visible. Hints go in `aria-describedby`, not in the label.

### Tab and segmented control

Dashboard: nav tab buttons, plain buttons in a `nav` landmark. Android: `SvcsSegmented` (`Role.Tab`, selected state) and the More tab strip (`selectable`, `Role.Tab`). Exactly one is selected. The selected one is shown with color and an underline or fill, and is also exposed as selected.

### Mode card

Dashboard `.preset-card`, a radio group (`widgets.js`): one tab stop, arrow keys move the choice, Space or Enter picks it, `aria-checked` follows the existing `selected` class. Locked while a job runs (`aria-disabled`). Android equivalent is `SvcsChip` inside a row, exposed as a radio button.

### Stat card

Dashboard `.stat-card` tiles, Android `SvcsStat`. A small caps label, a large number, an optional unit line. The label and value must read as one item, for example "Elapsed 0:08". Color accents the top edge only; the number is always readable text.

### Status pill

Dashboard `#status-pill` (`role="status"`, polite live region) and Android `SvcsStatusPill`. Always a dot plus a word (Encoding, Done, Failed, Offline). Color is never the only signal. States: idle or offline, running or live, done, failed.

### Saved card

Android `CompressLibraryScreen` card. Thumbnail (tap to play, labelled "Play video"), file name, before and after sizes, a savings figure, and Share and Delete actions at 48dp (tapping the thumbnail plays the video). The savings figure follows one rule everywhere: 5% or more is green, 0 to 4% is grey with a one line reason, negative is orange and says larger. The Done screen after compressing uses the same rule.

## Status messages

Result and error text on the dashboard (encryption, streaming, upload, drive, keygen) is colored green or red, and the words say what happened. Those containers are polite live regions (`widgets.js`) so the message is announced. Critical failures use `#error-banner`, which is `role="alert"`.

## Light theme

Both apps support a light theme. Dark is still the home of the design, and the dashboard stays dark unless the system or the user asks otherwise.

Dashboard: `static/js/theme.js` (loaded in the head so the page does not flash) sets `html[data-theme]` from the saved choice, or from the system setting when there is none. The header button flips it and remembers the choice in `localStorage` (per browser). The light values are in one block at the end of the template's `<style>`, under `html[data-theme="light"]`. Android: the app follows the system light or dark setting. `Color.kt` holds `SvcsDarkPalette` and `SvcsLightPalette`, and every `Svcs...` name is a composable getter that reads the active palette, so those names can only be read from composable code.

Light values (the same on both platforms):

| Role | Value | Note |
| --- | --- | --- |
| Background, surfaces | #f3f6fa, #ffffff, #eaf0f7, #e1e9f2 | |
| Border, bright border, control border | #b9c8da, #9db2cb, #587394 | control border 4:1 or better |
| Primary accent | #8f5400 | darker than dark mode's #ffb900 so it reads as text on white; buttons use white text |
| Accent text, green, teal, yellow, purple, red | #7d4a00, #09694a, #08706a, #6f5600, #6a3fc2, #b71c1c | each 4.8:1 or better on all four surfaces |
| Orange (Android warnings), blue (Android) | #a34700, #0b5aa8 | |
| Text, dim text, bright text | #14233a, #475a73, #0a1626 | dim text 5.7:1 or better |

Dashboard per-tab accents are tokens too (`--tab-library`, `--tab-autocompress`, `--tab-tools`) so JS and CSS never hardcode them. Use the tokens in new code. Hardcoded colors left on purpose: video player backgrounds (#000), modal scrims, and the vehicle color swatches (data, not theme). The metrics chart reads its colors when it is built, so a theme change shows on the next time the METRICS tab opens.