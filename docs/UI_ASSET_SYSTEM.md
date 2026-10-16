# Crosshair UI assets: system icons and static wallpaper

**Implemented source contract, Wave007:** [Tabler Icons](https://github.com/tabler/tabler-icons) is the primary system-icon source for Shell. The selected outline SVGs and original MIT notice come from pinned commit [`a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d`](https://github.com/tabler/tabler-icons/tree/a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d). The upstream [README](https://github.com/tabler/tabler-icons/blob/a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d/README.md) defines a24×24 grid and2px outline stroke. Only18 selected files were downloaded; there is no full catalog, icon font, SVG parser or SVG rendering library in firmware.

Exact source bytes, URLs, sizes, SHA-256 hashes, raster parameters, tool versions, generated-source/mask hashes and per-size results are recorded in [PROVENANCE.json](../shell/assets/tabler/PROVENANCE.json). The complete original [MIT licence](../shell/assets/tabler/LICENSE) retains `Copyright (c) 2020-2026 Paweł Kuna`; own generator/drawing code remains project MIT. This does not assign Tabler's licence to the separate owner-provided artistic reference.

## Stable bounded catalog

These are asset IDs, not process identities, capabilities or claims of implemented services. IDs are explicit `repr(u16)` values in [generated IconId](../shell/src/icon_assets.rs). Existing Shell role IDs0..5 are unchanged.

| ID / IconId | Selected upstream outline | Current role or catalog purpose |
|---|---|---|
|0 Applications|layout-grid|Desktop/Launcher applications|
|1 Today|calendar|Today view; no invented current date|
|2 Settings|settings|Interface settings|
|3 Diagnostics|activity|Actual supplied diagnostic counters|
|4 Information|info-circle|About|
|5 SwitchView|switch-horizontal|Opened-view switching|
|6 Home|home|Home/navigation asset|
|7 Back|arrow-left|Back/navigation asset|
|8 Up|chevron-up|Navigation asset|
|9 Down|chevron-down|Navigation asset|
|10 Left|chevron-left|Navigation asset|
|11 Right|chevron-right|Navigation asset|
|12 Menu|menu-2|Menu asset|
|13 Folder|folder|Future file UI asset; filesystem absent|
|14 Phone|phone|Future phone UI asset; modem service absent|
|15 Messages|messages|Future messaging UI asset; messaging service absent|
|16 Clipboard|clipboard|Clipboard/content action asset|
|17 Calculator|calculator|Calculator asset; no calculator app is added by this catalog|

Only the implemented Shell actions are presented as working applications. Keeping a small reusable asset available does not install its corresponding application. Cozette text/font bytes and all historical diagnostic theme tokens remain unchanged.

## Build-time transformation and runtime format

The [generator](../shell/tools/generate_icons.py) first verifies source/license/renderer-lock hashes, IDs and paths. Its bounded validator accepts only the exact24×24 outline root attributes and at most32 finite-coordinate `path` elements. It rejects DTD/entities, scripts, links/CSS/external resources, other elements, oversized files/paths and unsupported attributes before invoking CairoSVG. It rebuilds the allowlisted tree without upstream comments/metadata and substitutes white for `currentColor`; all source SVG files themselves remain byte-identical. A renderer fetch callback rejects all resource fetches. Generation/checking performs no network access and never executes SVG content.

Each of the18 sources is rasterized independently at12,16 and24px. Pinned CairoSVG renders at8× target resolution; the alpha channel is reduced with Pillow BOX filtering, then coverage `>=96` of255 becomes a foreground bit. The generated result is a crisp one-bit mask; there is no alpha blending, SVG evaluation, runtime scaling or background bitmap in the guest. Native small-size masks and actual Shell light/night captures were visually inspected; execution/pixel evidence belongs to [Wave007](../reports/WAVE_007.md).

Mask packing is continuous **row-major, MSB first**: pixel `(x,y)` uses bit `y*width+x`, byte `bit/8`, mask `0x80>>(bit%8)`. Each icon stores12px18B,16px32B,24px72B consecutively,122B per icon;18 icons therefore store exactly **2196B raw read-only mask data**. The [runtime drawing adapter](../shell/src/icons.rs) draws set-bit runs into the existing clipped `Surface` using one caller-supplied theme color. `draw_icon` rejects unsupported sizes; `IconId::from_u16` rejects unknown catalog IDs. Its loops are bounded by24×24 and use no allocation, MMIO or second framebuffer. The previous `draw(...kind,ink,accent)` signature stays compatible; monochrome foreground uses `ink`, while the retained accent argument creates no additional stored bitmap.

There is **0B new mutable persistent icon state**: mask data is a single static read-only allocation, color/position are call arguments and mask slice metadata is temporary.2196B is the raw data budget, not the whole linked image delta: generated lookup/drawing code, alignment and removal of the former procedural icons affect actual ELF/flat sizes. Final linked ROM/RAM accounting in [Wave007](../reports/WAVE_007.md) measures those separately. SVG/JSON/lock/license files are host/source provenance and are not embedded in User firmware.

## Reproducible commands and checks

Normal builds need only Python's standard library and the checked-in generated Rust:

```sh
python3 shell/tools/generate_icons.py --check
python3 shell/tools/test_generate_icons.py -v
```

`--check` binds exact selected SVGs, original licence, renderer locks, stable catalog/raster parameters, generator source, generated Rust and packed-mask bytes. It deliberately does not claim to rerasterize or independently prove the image from a repeated hash. The six parser/binding tests mutate source/licence/generated bytes and IDs/paths, reject active/unbounded input, and check every truncated prefix of the selected grid SVG.

Full regeneration is a separate host-only operation. [requirements.txt](../shell/assets/tabler/requirements.txt) pins all nine Python packages with PyPI artifact SHA-256 hashes; [requirements.lock.json](../shell/assets/tabler/requirements.lock.json) records the official release metadata URLs and allowed artifacts. Use Python3.12 and native Cairo **1.18.4**; CairoSVG2.8.2, Pillow12.3.0 and every dependency version are checked before rasterization. A different environment fails rather than silently updating generated masks.

```sh
python3.12 -m venv local/icon-tools
local/icon-tools/bin/python -m pip install --require-hashes -r shell/assets/tabler/requirements.txt
local/icon-tools/bin/python shell/tools/generate_icons.py --regenerate-check
# Deliberate reviewed asset update only:
local/icon-tools/bin/python shell/tools/generate_icons.py --generate
```

Native Cairo must already be installed separately; no Cairo source build or global Python installation is required by the project. Regeneration checks all54 masks and exact generated Rust byte for byte against the pinned output. Any tool upgrade, source/catalog/raster change or generated mismatch requires deliberate provenance/test review. Hashes establish consistency, not author authentication or a general-purpose SVG sandbox.

The Shell host suite adds catalog-size/ID/mask-bound checks plus tint/clipping/invalid-size/canary tests to the existing navigation tests. [Build/tests](../scripts/test-shell-ui.sh) run the offline checks and, when the pinned local tool environment exists, full regeneration. The [Shell build](../scripts/build-shell.sh) also checks asset bindings before compiling. Wave001–Wave006 and Wave004 UI golden bytes remain separate unchanged regressions. The Wave007 Tabler change affected its icon pixels; Wave007.1 separately changes Shell composition and adds the following wallpaper.

## Wave007.1 static wallpaper

The [original generated image](../shell/assets/wallpaper/crosshair-mist-source.png) and [creation prompt](../shell/assets/wallpaper/PROMPT.txt) are separate project resources, not a crop of the owner-approved reference or a background containing drawn interface controls. [Wallpaper provenance](../shell/assets/wallpaper/PROVENANCE.json) records source/prompt hashes, generation origin and applicable project terms, preserving the separate reference's rights. The reference remains unchanged. Tabler remains the primary system-icon source; this image supplies only the workspace background.

The [build-time generator](../shell/tools/generate_wallpaper.py) resizes to240×320 with LANCZOS, quantizes16 colors with Pillow MEDIANCUT without dithering, truncates RGB888 to RGB565 and derives a dark palette by multiplying each RGB565 channel by3/4. The recorded generation environment used Python3.12.14; the generator enforces Pillow12.3.0 and checks regenerated bytes exactly. The existing [hash-pinned Pillow artifacts](../shell/assets/tabler/requirements.txt) also cover this dependency; the normal source/output check needs only the standard library.

Each row uses independent one-byte packets: upper four bits are run length minus one (1..16), lower four bits are palette index (0..15). A321-entry little-endian u16 row table jumps to the requested row; two16-color RGB565 palettes serve classic/night themes. Generated payload is14827B run data +642B offsets +64B palettes = **15533B read-only data**. The [safe decoder](../shell/src/wallpaper.rs) accepts no files or externally supplied encoded buffer, checks row/slice bounds and writes clipped runs directly into the borrowed Surface. No expanded row/full-image buffer, runtime PNG/SVG decoder, allocation or second framebuffer is introduced. Scalar loop variables are temporary stack work; the asset adds no mutable palette or image buffer.

```sh
python3 shell/tools/generate_wallpaper.py --check
python3 shell/tools/test_generate_wallpaper.py -v
local/icon-tools/bin/python shell/tools/generate_wallpaper.py --regenerate-check
```

Hash/source validation, corrupted-format tests and full regeneration are distinct checks. The guest's DrawStats/RenderStats count actual software decode/write work per region; they do not measure wall time or change the current full153600B Present transfer. Full Desktop entry decodes only workspace y24..296. Focus changes restore old/new shortcut regions, menu opening/focus leaves wallpaper untouched, and dismissal restores a bounded covered union. Tests compare these incremental frames byte for byte with fresh full composition. Firmware extent, persistent Shell/observation RAM and display publication remain separately measured categories.
