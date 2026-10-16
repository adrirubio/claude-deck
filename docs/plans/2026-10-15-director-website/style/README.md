# The chosen style: option C, "Floor" (revised)

The Director chose this art direction on 2026-10-16 (#745). It is a style frame, not the finished design: the build replaces its placeholder motion and polishes its illustrations.

- `index.html`: the style frame, self-contained (fonts embedded, no external requests). Open it in a browser.
- `source.html`: the same page before the fonts are embedded (`/*FONTS:...*/` marks where they go).

## What the style fixes
- **The world:** an isometric factory floor drawn in code (SVG).
- **Type:** Instrument Serif for headlines, Instrument Sans for text.
- **Colour roles:** people amber (`#E3962B`), AI agents verdigris (`#1E8C76`), systems steel (`#9DAEB6`) and graphite (`#1C2A31`), on fog (`#ECEFF1`).
- **Features:** each feature has its own colour and AI cap shape (blue `#2E7DD7` cube, violet `#8E5BD8` pyramid, rose `#D0577B` cylinder). AI bodies stay verdigris.
- **Two pictures:** the hero shows the factory from outside (the Director, an AI helper, GitHub, Deck and several AI teams); the second scene shows the inside (parallel lanes through an AI team).

## Fonts
Instrument Serif and Instrument Sans are under the SIL Open Font License 1.1 (via Fontsource). They are embedded as WOFF2 data in `index.html`.
