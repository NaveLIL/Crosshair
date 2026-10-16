# Public repository pack

`scripts/pack-repomix.sh` packages the current **public checkout**, including its source, build configuration, documentation, licences and accepted text reports. It requires the installed Repomix **1.18.0** and never installs dependencies, clones a remote, reads the private parent repository, embeds Git history or publishes anything.

```sh
scripts/pack-repomix.sh
scripts/pack-repomix.sh --check-only
```

Run after implementation and evidence collection settle. The first command regenerates the versioned [asset manifest](ASSET_MANIFEST.json), then creates ignored `target/artifacts/repomix/crosshair-public.json`, `manifest.json` and `repomix.log`. If the asset manifest changes, commit it with the public work and run the pack again against the final commit. `--check-only` checks the existing package and manifest against the current source bytes and HEAD.

The explicit input inventory comes from `git ls-files --cached --others --exclude-standard`. It includes current tracked files and nonignored new public files; tracked deletions are absent. The script rejects symlinks, unexpected generated binaries and private/cache paths. It never traverses the ignored `local/`, `target/`, `private/`, `work/` or toolchain directories. Generated packs exclude themselves.

All UTF-8 text files must appear in Repomix's JSON `files` map. This includes `.cargo` configuration and `.log` evidence; generic default exclusions are disabled so reports are not silently dropped. The script compares each packed body to its source and rejects missing or changed text. Repomix1.18.0 applies outer whitespace `String.trim`; this is the only permitted text transformation. Comments, implementations, empty lines and base64 text are retained. The manifest records each original byte length and SHA-256 separately.

Public PNG/JPEG/GIF/WebP assets and verified240×320 Wave007 raw565 framebuffer captures appear in the directory tree and [asset manifest](ASSET_MANIFEST.json), with their original lengths, media types and SHA-256 hashes. Their binary bytes are not embedded in the text pack. Asset hashes do not grant a licence: the approved visual reference retains the rights and provenance described in [UI Design System](UI_DESIGN_SYSTEM.md), and third-party notices remain in place. Runtime ELF/BIN, private dumps and caches stay outside the text pack. The raw565 allowance is restricted to `reports/wave007/frames/`, exact153600-byte RGB565_LE frames; their geometry is included in the asset manifest.

The pinned [configuration](../repomix.config.json) keeps Repomix's Secretlint check enabled. Any omitted file, content mismatch, changed input during packaging or scanner failure stops completion. The final `manifest.json` records the public HEAD, pinned CLI version, configuration hash, original file hashes, package length and package SHA-256. This is a whole-public-tree review artifact, not a substitute for guest test evidence or [publication policy](../RIGHTS_AND_PUBLICATION.md).

Repomix's documented input/output, ignore, binary-handling and security options are in its [official configuration guide](https://repomix.com/guide/configuration). The installed1.18.0 CLI/help and implementation were checked for the JSON file map and mandatory outer whitespace trim.
