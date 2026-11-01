# Font provenance

`mona-sans-expanded.woff2` is a browser-compatible derivative of `MonaSansVF-Expanded[opsz,wght,ital].woff2` from GitHub's official Mona Sans repository. Its expanded outlines are preserved without alteration.

- Source: https://github.com/github/mona-sans/blob/4bc6ba8b354c36b4fb66d32cd67b4c1f2beb0a06/fonts/webfonts/variable/MonaSansVF-Expanded%5Bopsz%2Cwght%2Cital%5D.woff2
- Upstream commit: `4bc6ba8b354c36b4fb66d32cd67b4c1f2beb0a06`
- Original upstream SHA-256: `db14d029150bc7c75c7715ec52c9004ab98b5da70081c3c68e43501a00c42ed2`
- Shipping derivative SHA-256: `7c62f92f8585b0ed99f18ab057ec167bdfbe54815b678b8dee69719bb5421d06`
- License: SIL Open Font License 1.1; see `OFL.txt`.
- Variable axes: `wght` 200-900, `opsz` 0-100, `ital` 0-1. The font file already contains expanded-width outlines; no CSS width transformation is needed.
- Modification: removed the optional `STAT` style metadata table because its invalid axis references caused Chromium's OpenType Sanitizer to reject the upstream file. No glyph outlines, layout tables, metrics, or variation data were changed. FontTools performed the WOFF2 reserialization.
- Modified-version primary internal name: `FoodLens Expanded`, respecting the upstream Reserved Font Name under the OFL. Name IDs 1, 2, 3, 4, 6, 16, 17, and 25 were updated where present. Original copyright and license metadata remain intact.
- CSS family alias: `Mona Sans Expanded`; declare weight 200 900 and normal style for the upright face. An italic face can reuse the file with `font-style: italic` when needed. This alias identifies the original requested design while the redistributed derivative's internal primary name is `FoodLens Expanded`.
- Validation: Chromium successfully loaded the resulting FontFace at weights 200, 400, 550, 650, 750, and 900, with no browser console errors.

The v2 interface reuses the existing self-hosted Geist Mono asset from `/static/fonts/geist-mono.woff2` for technical metadata and measurements. Its upstream license accompanies that file.
