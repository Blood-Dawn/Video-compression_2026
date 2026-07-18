# SVCS Mobile - imported design

Vendored from the Claude Design project **"Mobile app conversion plan"**
(`19ed3076-4995-417d-8281-b994f732fa83`) on 2026-07-18, via the `DesignSync` MCP.

This directory is the design source of truth for `mobile/android`. It is a
one-way import: **do not hand-edit these files.** Re-import instead, so the app
and the design project cannot silently drift apart.

## Contents

| Path | What it is |
| --- | --- |
| `SVCS-Mobile.dc.html` | The full phone mockup. Renders in a 412x892 Android device frame. |
| `tokens/colors.css` | Surfaces, borders, accents, status colors, text, semantic aliases. |
| `tokens/typography.css` | Families, weights, letter-spacing, type scale. |
| `tokens/spacing.css` | Spacing scale, radius, borders, shadows, glow, motion, layout constants. |
| `tokens/effects.css` | CRT scanline overlay and the shared keyframes. |
| `tokens/fonts.css` | Google Fonts `@import`. **Not shippable as-is;** see the warning in the file. |

Not imported: `android-frame.jsx` and `support.js` are mockup scaffolding (the
device bezel and the Design renderer), not product UI. `_ds_bundle.js` and
`_ds_manifest.json` are the Design tool's own compiled artifacts.

## What the mockup specifies

Five bottom-nav tabs: **HOME, LIBRARY, LIVE, METRICS, MORE**, plus a
`videoDetail` screen pushed from LIBRARY, an upload sheet, and a notifications
screen.

The mockup is a **visual** spec. It contains mock data and no `/api/` calls, so
it defines layout, copy, and states, not wiring. Endpoint mapping is in
`docs/MOBILE-ARCHITECTURE.md`.

## The decisive constraint it encodes

The mockup settles the biggest open question of the port. Verbatim copy from it:

> "Files are processed on your local SVCS server."
> "Credentials are sent only to your local SVCS server and are never logged."
> "Tap to pick a clip from your device, or point SVCS at a server file path."
> Settings fields: **Server Address**, **Access Token**
> METRICS tile: "POWER DURING ENCODING / server draw - avg watts"

So the Android app is a **thin client**: it drives and monitors the existing
SVCS server over its REST API. It does not run FFmpeg, OpenCV, or ONNX
on-device. That is what makes the port tractable rather than a rewrite, and it
is why the existing ~21k lines of Python stay exactly where they are.

## Carrying the tokens into Android

The tokens are plain CSS custom properties, so they port mechanically to a
Compose theme. Two things do NOT carry over:

1. **`--sidebar-w: 340px`** is desktop chrome. The phone layout has no sidebar.
2. **`tokens/fonts.css`** fetches from a CDN. Bundle the three OFL-1.1 families
   under `res/font/` instead and ship their license text. See the file's header.

The design system's own writing convention matches this repo's house rule and is
restated here so it survives the import: **ASCII hyphens only, never em-dashes
or en-dashes**, in code, comments, docs, and UI strings alike.
