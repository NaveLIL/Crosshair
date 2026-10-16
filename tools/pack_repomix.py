#!/usr/bin/env python3
"""Pack every current public text file and audit binary assets with Repomix1.18.0.

Requires the installed pinned CLI; never installs packages or reads parent Git
history. The combined pack stays ignored under target/artifacts/repomix. Its
manifest binds every original file by SHA-256, while a versioned asset manifest
records public images without embedding their bytes into the text package.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.18.0"
ASSETS = "docs/ASSET_MANIFEST.json"
OUTPUT = ROOT / "target/artifacts/repomix"
DENIED_TOP = {".git", "target", "local", "private", "work", "node_modules"}
DENIED_SUFFIX = {".elf", ".bin", ".rgb565", ".iso", ".vmdk", ".vmem", ".vmsn",
                 ".vmss", ".nvram", ".nbf", ".nba", ".cab", ".exe", ".dll", ".zip", ".7z"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".raw565": "image/x-rgb565-le"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def public_inventory():
    require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() == ROOT,
            "Pack script must run in its own public repository")
    require(git("remote", "get-url", "origin").decode().strip()
            in ("https://github.com/NaveLIL/Crosshair.git", "https://github.com/NaveLIL/Crosshair"),
            "Expected public Crosshair origin; refusing another checkout")
    names = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""}
    text, images, original = {}, [], {}
    for name in sorted(names):
        path, relative = ROOT / name, PurePosixPath(name)
        require(not relative.is_absolute() and ".." not in relative.parts and "\n" not in name and "\r" not in name,
                "Unsafe public filename: " + name)
        require(relative.parts[0] not in DENIED_TOP and "__pycache__" not in relative.parts
                and relative.name != ".DS_Store"
                and not relative.name.startswith("repomix-output") and relative.suffix.lower() not in DENIED_SUFFIX,
                "Private/cache/generated binary unexpectedly tracked or unignored: " + name)
        require(not path.is_symlink(), "Symlinks are not packed: " + name)
        if not path.exists():
            continue  # A tracked deletion is absent from the current tree.
        require(path.is_file() and path.resolve().is_relative_to(ROOT), "File escapes public checkout: " + name)
        if name == ASSETS:
            continue  # Regenerated below from this exact inventory.
        data = path.read_bytes()
        original[name] = {"bytes": len(data), "sha256": digest(data)}
        if relative.suffix.lower() in IMAGE_TYPES:
            asset = {"path": name, "media_type": IMAGE_TYPES[relative.suffix.lower()], **original[name]}
            if relative.suffix.lower() == ".raw565":
                require(any(name.startswith(prefix) for prefix in
                            ("reports/wave007/frames/", "reports/wave007-1/frames/", "reports/wave007-2/frames/"))
                        and len(data) == 240 * 320 * 2,
                        "Only bounded verified Shell framebuffer captures may use raw565: " + name)
                asset.update(width=240, height=320, stride_pixels=240, pixel_format="RGB565_LE")
            images.append(asset)
        else:
            require(b"\0" not in data, "Unexpected non-image binary public file: " + name)
            try:
                text[name] = data.decode("utf8")
            except UnicodeDecodeError as error:
                raise ValueError("Unexpected non-UTF8 public file: " + name) from error
    asset_data = (json.dumps({
        "scope": "Current public repository binary image assets; SVG remains full UTF-8 text in the pack. Hashes identify original bytes, not a licence grant",
        "licensing": "See each asset's provenance and adjacent documentation. Crosshair code MIT does not automatically relicense reference artwork or third-party assets.",
        "assets": images,
    }, indent=2) + "\n").encode()
    text[ASSETS] = asset_data.decode()
    original[ASSETS] = {"bytes": len(asset_data), "sha256": digest(asset_data)}
    return text, images, original, asset_data


def trim_like_repomix(text):
    # Repomix1.18.0 always applies ECMAScript String.trim, even when optional
    # comment/empty-line transformations are off. Original bytes remain hashed.
    whitespace = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
    return text.strip(whitespace)


def verify_pack(package, texts):
    require(isinstance(package.get("files"), dict), "Missing Repomix JSON file map")
    require(set(package["files"]) == set(texts), "Repomix omitted or added public text files")
    for name, expected in texts.items():
        require(package["files"][name] == trim_like_repomix(expected),
                "Repomix changed public file contents beyond documented outer whitespace trim: " + name)
    require("gitDiffs" not in package and "gitLogs" not in package, "History/diffs must not be embedded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true", help="Verify existing output against current public files without repacking")
    mode.add_argument("--manifest-only", action="store_true", help="Refresh binary asset inventory before committing, without creating a pack")
    args = parser.parse_args()
    text, images, original, asset_data = public_inventory()
    if args.manifest_only:
        (ROOT / ASSETS).write_bytes(asset_data)
        require(public_inventory()[3] == asset_data, "Binary assets changed while manifest was being written")
        print(f"Refreshed {ASSETS}: {len(images)} public image assets; no pack created")
        return
    command = shutil.which("repomix")
    require(command is not None, "Install Repomix1.18.0 explicitly; pack script does not install dependencies")
    require(subprocess.check_output([command, "--version"], text=True).strip() == VERSION,
            "Need pinned Repomix1.18.0; refusing an unverified CLI version")
    pack_path, manifest_path = OUTPUT / "crosshair-public.json", OUTPUT / "manifest.json"
    if not args.check_only:
        (ROOT / ASSETS).write_bytes(asset_data)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        # Passing the complete explicit inventory keeps accepted .log reports,
        # dotfiles and images' tree entries while excluding ignored build caches.
        names = sorted(set(text) | {asset["path"] for asset in images})
        process = subprocess.run([command, "--config", str(ROOT / "repomix.config.json"), "--stdin",
                                  "--output", str(pack_path), "--quiet"], cwd=ROOT,
                                 input=("\n".join(names) + "\n").encode(), capture_output=True)
        (OUTPUT / "repomix.log").write_bytes(process.stdout + process.stderr)
        require(process.returncode == 0, "Repomix failed; inspect target/artifacts/repomix/repomix.log")
    require((ROOT / ASSETS).read_bytes() == asset_data, "Public binary asset manifest is stale")
    packed_bytes = pack_path.read_bytes()
    verify_pack(json.loads(packed_bytes), text)
    current_text, current_images, current_original, current_assets = public_inventory()
    require((current_text, current_images, current_original, current_assets) == (text, images, original, asset_data),
            "Public sources changed while Repomix was packing; rerun after work settles")
    expected = {
        "result": "PASS", "repomix_version": VERSION,
        "scope": "All current tracked and nonignored public text; image paths and binary hashes, no private parent/history or generated binaries",
        "source_head": git("rev-parse", "HEAD").decode().strip(),
        "text_files": len(text), "image_assets": len(images),
        "content_transform": "Repomix1.18.0 outer String.trim only; no compression/comment removal/base64 truncation",
        "original_files": original,
        "pack": {"path": "crosshair-public.json", "bytes": len(packed_bytes), "sha256": digest(packed_bytes)},
        "configuration_sha256": digest((ROOT / "repomix.config.json").read_bytes()),
    }
    if args.check_only:
        require(json.loads(manifest_path.read_text()) == expected, "Pack manifest is stale or mismatched")
    else:
        manifest_path.write_text(json.dumps(expected, indent=2) + "\n")
    print(f"{'Verified' if args.check_only else 'Packed'} {len(text)} public text files and {len(images)} image assets with Repomix{VERSION}")
    print(f"Pack: target/artifacts/repomix/crosshair-public.json ({len(packed_bytes)} bytes, SHA256 {digest(packed_bytes)})")


if __name__ == "__main__":
    main()
