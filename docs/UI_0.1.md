# UI 0.1: software primitives, RGB565 and Cyrillic

Implemented and tested after the E2A execution gate on 2026-10-16. This is an independent drawing library and a 240×320 host rendering fixture. It is not a desktop, an ATI W3200 driver, touchscreen calibration, or a hardware-tested UI.

## API and memory contract

[`crosshair-ui`](../ui/Cargo.toml) is a dependency-free `#![no_std]` library with `#![forbid(unsafe_code)]`. It has no allocator, MMIO, OS calls, display singleton, interrupt state or second framebuffer.

`Surface::new(&mut [u16], width, height, stride)` checks nonzero dimensions up to 240×320, `stride >= width`, checked span multiplication, backing length and the **153600-byte maximum framebuffer span**. An exclusive borrow prevents independent mutable aliases. Row padding is preserved. Smaller surfaces/strips are supported using their own local coordinates; no implicit full-screen copy is allocated. The kernel caller must supply BSS/RAM or a strip, never a 153600-byte automatic array on its 16 KiB kernel stack. The host example owns exactly one framebuffer in a `Vec`; that allocation is not part of the library.

Drawing methods: `fill`, `fill_rect`, one-pixel `stroke_rect`, `pixel`, clipped Bresenham `line`, and transparent `text`. Coordinates may be negative. Rectangle calculations use widened/saturating arithmetic; line intersections use bounded i128 integer arithmetic for the full i32 endpoint range, followed by at most the surface's longest dimension of raster steps. Intersections truncate toward zero. RGB888 conversion truncates to numeric RGB565; transfer byte order is the display adapter's responsibility. The fixture writes little-endian raw565.

Eight dirty rectangles are stored inline. Touching/overlapping rectangles merge; exceeding capacity coalesces their union, including the new rectangle. Extra clean pixels may be transferred, but dirty pixels are not dropped. A new surface starts fully dirty. `present(callback)` gives each rectangle, a shared view of the same framebuffer, and stride. Dirty state clears **only after every callback succeeds**; any error retains all rectangles for retry, including ones already sent. A retry must therefore be idempotent. Returning `Ok` means the backend finished consuming those pixels; merely queueing asynchronous DMA is not a completed present. There is no asynchronous transport implementation here.

## Font provenance

The checked-in subset contains ASCII U+0020–007E, Russian U+0410–044F plus Ё/ё, U+2014 and U+FFFD: **163 glyphs**, including Й/й, Ъ/ъ and Ь/ь. Text walks Unicode scalar values, not UTF-8 bytes. Unknown characters use U+FFFD; newline resets x and advances 14 pixels.

Source: [Cozette v.1.30.0 BDF](https://github.com/the-moonwitch/Cozette/releases/download/v.1.30.0/cozette.bdf), commit `d2282e728aa64949b0a1e6489920ceb0772944fa`, SHA-256 `8d740166af3a14053773ac7a8846bf288c8818a44f73ab28d4725d91b03a5639`, 683147 bytes. The original [MIT notice](../ui/third_party/cozette/LICENSE) and [provenance](../ui/third_party/cozette/PROVENANCE.json) remain separate from Crosshair's own license.

The [generator](../ui/tools/subset_font.py) preserves BDF ink offsets and baseline in 8×13 byte rows with a 6-pixel advance. Cropping to six pixels would lose overhangs in Д/Щ/д/щ, `4`, `q` and other selected glyphs. Bitmap rows occupy 2119 bytes; the codepoint lookup adds 652 bytes. The full 683147-byte BDF is **not committed** and is not a build dependency.

```sh
# Optional download of the pinned source and deterministic regeneration:
python3 ui/tools/subset_font.py
# Check an independently retained, read-only copy without a network request:
python3 ui/tools/subset_font.py --input /path/to/cozette.bdf --check
```

Input length/SHA are checked before parsing; the generator rejects cropped ink, duplicate/missing selected glyphs and an output equal to its input. Runtime builds use only the generated Rust table.

## Reproduction and evidence

```sh
scripts/bootstrap-rust.sh
RUSTUP_HOME="$PWD/local/toolchains/rustup" scripts/test-ui.sh
```

The script calls the installed pinned Cargo/rustc directly; it does not install a global toolchain. Host Cargo runs from a fresh directory outside the repository with an absolute UI manifest and explicit host target. This avoids inherited `build.target`, merged `unstable.build-std` arrays and the kernel's BSP-selecting build script. The separate UI workspace and lockfile do not change the kernel manifest. ARM verification then runs from the repository root with its existing ARMv5TE/core build configuration.

**Verified:** 11 host tests cover stride and sentinel guards, invalid dimensions/overflow/budget, negative/extreme clipping, line/stroke pixel matrices, RGB565 primaries, complete Russian coverage and ink overhang, Unicode fallback/newline, dirty overflow, failed-present retry and clear only after full success. A reviewed full-frame little-endian raw565 FNV-1a golden is `5431880093368634183`; sampled primary-color pixels are checked independently. The PNG has been visually inspected at its actual 240×320 size. The deterministic font generator's `--check` was actually run against the pinned BDF and passed. The library was compiled for `armv5te-none-eabi`; its actual code object has ARMv5TE attributes, ARM EABI5 and no hard-float flag. This is compile verification, not ARM execution of the renderer.

Outputs are ignored generated files: `target/artifacts/ui/primitives.raw565`, `primitives.png`, `tests.log`, `arm-build.log`, `arm-lib-report.txt`, `font-generator-check.json` and `validation.json`. The [PNG encoder](../tools/framebuffer_png.py) uses Python's standard library, streams rows and preserves RGB565 bit expansion; it allocates no second full framebuffer. A retained upstream BDF under that ignored artifact directory enables the script's optional regeneration check. A fresh offline source checkout still builds and runs the UI tests without it.

## Next input/display contract

Future display code consumes dirty rectangles through the present callback; MMIO access, pixel ordering, cache/DMA completion and failure recovery belong to its BSP. Future focus must stay visible, and stylus and hardware QWERTY must converge on the same logical action/state path. Key press/release/repeat, Fn/layout and text input remain separate from drawing. A stylus coordinate requires a proven calibration/input driver before becoming a UI action. These are documented integration constraints; no empty focus/input/controller interfaces have been added.
