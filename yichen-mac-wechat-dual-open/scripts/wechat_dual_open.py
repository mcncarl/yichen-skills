#!/usr/bin/env python3
"""Create and maintain a second macOS WeChat app."""

from __future__ import annotations

import argparse
import colorsys
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_SOURCE = Path("/Applications/WeChat.app")
DEFAULT_TARGET = Path("~/Applications/WeChat-2.app").expanduser()
DEFAULT_BUNDLE_ID = "com.tencent.xin2"
DEFAULT_LANGUAGES = ["zh-Hans", "en"]


def run(args: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    kwargs = {
        "check": check,
        "text": True,
    }
    if capture:
        kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT})
    return subprocess.run(args, **kwargs)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Missing required macOS tool: {name}")
    return path


def plist_path(app: Path) -> Path:
    return app / "Contents" / "Info.plist"


def read_plist(path: Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


def write_plist(path: Path, data: dict) -> None:
    with path.open("wb") as f:
        plistlib.dump(data, f, sort_keys=False)


def app_version(app: Path) -> str:
    try:
        info = read_plist(plist_path(app))
        return info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "unknown"
    except Exception:
        return "unknown"


def bundle_id(app: Path) -> str:
    try:
        return read_plist(plist_path(app)).get("CFBundleIdentifier", "unknown")
    except Exception:
        return "unknown"


def embedded_app(target: Path) -> Path:
    return target / "Contents" / "MacOS" / "WeChatAppEx.app"


def outer_icon(target: Path) -> Path:
    return target / "Contents" / "Resources" / "AppIcon.icns"


def inner_icon(target: Path) -> Path:
    return embedded_app(target) / "Contents" / "Resources" / "app.icns"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def copy_app(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"Source app not found: {source}")
    if target.exists():
        raise SystemExit(f"Target already exists: {target}. Use repair, or delete/recreate only after user confirmation.")
    ensure_parent(target)
    shutil.copytree(source, target, symlinks=True)


def set_bundle_id(app: Path, new_id: str) -> None:
    info_path = plist_path(app)
    info = read_plist(info_path)
    info["CFBundleIdentifier"] = new_id
    write_plist(info_path, info)


def remove_icon_name(app: Path) -> None:
    for info_path in [plist_path(app), plist_path(embedded_app(app))]:
        if info_path.exists():
            info = read_plist(info_path)
            if "CFBundleIconName" in info:
                del info["CFBundleIconName"]
                write_plist(info_path, info)


def clear_finder_custom_icon(app: Path) -> None:
    """Remove Finder custom icon detritus before code signing.

    codesign rejects bundles that contain resource forks or FinderInfo. The
    custom icon can be re-added after signing for Finder display.
    """
    icon_file = app / "Icon\r"
    if icon_file.exists():
        icon_file.unlink()
    for path in [app, icon_file]:
        for attr in ["com.apple.FinderInfo", "com.apple.ResourceFork"]:
            run(["xattr", "-d", attr, str(path)], check=False, capture=True)


def codesign(app: Path) -> None:
    require_tool("codesign")
    clear_finder_custom_icon(app)
    result = run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=False, capture=True)
    if result.returncode != 0:
        raise SystemExit(result.stdout)


def register_and_refresh(app: Path) -> None:
    """Re-register the app with Launch Services and flush icon caches.

    Uses killall only for iconservicesagent (no visual disruption).
    Finder and Dock will pick up changes on next app launch or folder visit.
    """
    lsregister = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
    if lsregister.exists():
        run([str(lsregister), "-f", str(app)], check=False)
        ex = embedded_app(app)
        if ex.exists():
            run([str(lsregister), "-f", str(ex)], check=False)
    run(["qlmanage", "-r", "cache"], check=False, capture=True)
    # Only flush the icon service agent; avoid killing Finder/Dock to prevent
    # visual disruption for the user.
    run(["killall", "iconservicesagent"], check=False, capture=True)


def set_language(bundle: str, languages: list[str]) -> None:
    run(["defaults", "write", bundle, "AppleLanguages", "-array", *languages])


def launch(app: Path) -> None:
    exe = app / "Contents" / "MacOS" / "WeChat"
    if not exe.exists():
        raise SystemExit(f"WeChat executable not found: {exe}")
    subprocess.Popen([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def status(source: Path, target: Path) -> None:
    print(f"source: {source} exists={source.exists()} version={app_version(source)} bundle={bundle_id(source)}")
    print(f"target: {target} exists={target.exists()} version={app_version(target)} bundle={bundle_id(target)}")
    if target.exists():
        for p in [outer_icon(target), inner_icon(target)]:
            print(f"icon: {p} exists={p.exists()} size={p.stat().st_size if p.exists() else 'n/a'}")
    ps = run(["ps", "-axo", "pid,command"], check=False, capture=True).stdout or ""
    for needle in [str(source), str(target)]:
        rows = [line.strip() for line in ps.splitlines() if needle in line and "Contents/MacOS/WeChat" in line]
        print(f"running for {needle}: {len(rows)}")
        for row in rows[:5]:
            print(f"  {row}")


def create(source: Path, target: Path, new_bundle_id: str, languages: list[str]) -> None:
    copy_app(source, target)
    set_bundle_id(target, new_bundle_id)
    set_language(new_bundle_id, languages)
    remove_icon_name(target)
    codesign(target)
    register_and_refresh(target)
    print(f"created: {target}")


def repair(target: Path, new_bundle_id: str, languages: list[str]) -> None:
    if not target.exists():
        raise SystemExit(f"Target app not found: {target}")
    set_bundle_id(target, new_bundle_id)
    set_language(new_bundle_id, languages)
    remove_icon_name(target)
    codesign(target)
    register_and_refresh(target)
    print(f"repaired: {target}")


def import_pillow():
    try:
        from PIL import Image
    except Exception as exc:
        raise SystemExit(
            f"Pillow is required for icon recoloring.\n"
            f"Install it with: pip3 install Pillow\n"
            f"Original error: {exc}"
        ) from exc
    return Image


def extract_largest_png(icns: Path, work: Path) -> Path:
    require_tool("iconutil")
    iconset = work / "source.iconset"
    run(["iconutil", "-c", "iconset", str(icns), "-o", str(iconset)])
    candidates = sorted(iconset.glob("*.png"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidates:
        raise SystemExit(f"No PNG renditions extracted from {icns}")
    return candidates[0]


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise argparse.ArgumentTypeError("Use a 6-digit hex color such as #1296db")
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a 6-digit hex color such as #1296db") from exc


def recolor_green_to_blue(src_png: Path, out_png: Path, target_rgb: tuple[int, int, int]) -> None:
    Image = import_pillow()
    img = Image.open(src_png).convert("RGBA")
    target_h = colorsys.rgb_to_hls(*(c / 255 for c in target_rgb))[0]
    pix = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pix[x, y]
            if a == 0:
                continue
            h, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            hue = h * 360
            is_green = 70 <= hue <= 175 and sat > 0.18 and g > r * 1.04 and g > b * 1.04
            is_greenish_light = g > 135 and g > r + 14 and g > b + 10 and sat > 0.10
            if is_green or is_greenish_light:
                new_sat = min(1.0, max(sat * 1.03, 0.34 if light < 0.82 else sat))
                new_light = min(0.92, light + (0.035 if 0.25 < light < 0.72 else 0.0))
                nr, ng, nb = colorsys.hls_to_rgb(target_h, new_light, new_sat)
                pix[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
    img.save(out_png)


def build_icns(preview_png: Path, out_icns: Path) -> None:
    Image = import_pillow()
    require_tool("iconutil")
    img = Image.open(preview_png).convert("RGBA")
    iconset = out_icns.parent / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()
    for size in [16, 32, 128, 256, 512]:
        img.resize((size, size), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
        img.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(out_icns)])


def set_finder_custom_icon(app: Path, preview_png: Path, work: Path) -> None:
    """Set a Finder custom icon using Carbon-era tools if available.

    On macOS 13+ these tools (DeRez, Rez, SetFile) may not be present.
    The icns replacement alone is usually sufficient for Finder display,
    so this step is a best-effort enhancement, not a requirement.
    """
    for tool in ["sips", "DeRez", "Rez", "SetFile"]:
        if not shutil.which(tool):
            print(f"  note: skipping Finder custom icon ({tool} not found); icns replacement is sufficient")
            return
    custom_png = work / "custom-icon-source.png"
    rsrc = work / "custom-icon.rsrc"
    shutil.copy2(preview_png, custom_png)
    run(["sips", "-i", str(custom_png)], capture=True)
    with rsrc.open("w") as f:
        subprocess.run(["DeRez", "-only", "icns", str(custom_png)], check=True, text=True, stdout=f)
    icon_file = app / "Icon\r"
    if icon_file.exists():
        icon_file.unlink()
    run(["Rez", "-append", str(rsrc), "-o", str(icon_file)])
    run(["SetFile", "-a", "C", str(app)])
    run(["SetFile", "-a", "V", str(icon_file)])


def recolor_icon(source: Path, target: Path, blue: tuple[int, int, int], no_finder_custom_icon: bool) -> None:
    if not target.exists():
        raise SystemExit(f"Target app not found: {target}")
    source_icns = outer_icon(source)
    if not source_icns.exists():
        raise SystemExit(f"Source icon not found: {source_icns}")
    with tempfile.TemporaryDirectory(prefix="wechat-blue-icon-") as td:
        work = Path(td)
        src_png = extract_largest_png(source_icns, work)
        preview = work / "wechat-original-blue-preview.png"
        new_icns = work / "AppIcon.icns"
        recolor_green_to_blue(src_png, preview, blue)
        build_icns(preview, new_icns)

        for icon in [outer_icon(target), inner_icon(target)]:
            if icon.exists():
                backup = icon.with_name(icon.name + ".before-blue.bak")
                if not backup.exists():
                    shutil.copy2(icon, backup)
                shutil.copy2(new_icns, icon)

        remove_icon_name(target)
        preview_dest = target.parent / "WeChat-2-blue-icon-preview.png"
        shutil.copy2(preview, preview_dest)

    codesign(target)
    if not no_finder_custom_icon:
        with tempfile.TemporaryDirectory(prefix="wechat-finder-icon-") as td:
            set_finder_custom_icon(target, preview_dest, Path(td))
    register_and_refresh(target)
    print(f"recolored icon for: {target}")
    print(f"preview: {preview_dest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-app", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target-app", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    create_p = sub.add_parser("create")
    create_p.add_argument("--languages", nargs="+", default=DEFAULT_LANGUAGES)

    repair_p = sub.add_parser("repair")
    repair_p.add_argument("--languages", nargs="+", default=DEFAULT_LANGUAGES)

    lang_p = sub.add_parser("set-language")
    lang_p.add_argument("--languages", nargs="+", default=DEFAULT_LANGUAGES)

    icon_p = sub.add_parser("recolor-icon")
    icon_p.add_argument("--blue", type=hex_to_rgb, default=hex_to_rgb("#1296db"))
    icon_p.add_argument("--no-finder-custom-icon", action="store_true")

    sub.add_parser("refresh")
    sub.add_parser("launch")

    args = parser.parse_args()
    source = args.source_app.expanduser()
    target = args.target_app.expanduser()

    if args.command == "status":
        status(source, target)
    elif args.command == "create":
        create(source, target, args.bundle_id, args.languages)
    elif args.command == "repair":
        repair(target, args.bundle_id, args.languages)
    elif args.command == "set-language":
        set_language(args.bundle_id, args.languages)
        print(f"language preference set for {args.bundle_id}: {args.languages}")
    elif args.command == "recolor-icon":
        recolor_icon(source, target, args.blue, args.no_finder_custom_icon)
    elif args.command == "refresh":
        register_and_refresh(target)
        print(f"refreshed icon/app caches for: {target}")
    elif args.command == "launch":
        launch(target)
        print(f"launched: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
