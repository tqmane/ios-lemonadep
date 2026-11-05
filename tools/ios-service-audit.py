#!/usr/bin/env python3
"""Read-only App Store/service inventory for a locally mounted iOS root.

This does not test networking, authentication, or whether a daemon runs.
No Apple credentials or files are copied, and nothing is modified.
"""
from __future__ import annotations

import argparse
import json
import plistlib
from pathlib import Path

APP_PARENTS = (
    "Applications",
    "System/Applications",
    "private/preboot/Cryptexes/App/Applications",
    "private/preboot/Cryptexes/App/System/Applications",
    "private/preboot/Cryptexes/OS/Applications",
    "private/preboot/Cryptexes/OS/System/Applications",
)

JOB_DIRECTORIES = (
    "System/Library/LaunchDaemons",
    "System/Library/LaunchAgents",
    "System/Library/LaunchAngels",
    "Library/LaunchDaemons",
    "Library/LaunchAgents",
)

# Hints only: exact launchd job labels depend on iOS version.
SERVICE_HINTS = (
    "appstored", "itunesstored", "amsaccountsd", "accountsd",
    "akd", "apsd", "nsurlsessiond", "trustd", "mDNSResponder",
    "mobileactivationd", "installd", "fairplayd",
)


def read_plist(path: Path, warnings: list[str]):
    try:
        with path.open("rb") as stream:
            return plistlib.load(stream)
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as exc:
        warnings.append(f"cannot parse {path.name}: {type(exc).__name__}")
        return None


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def find_apps(root: Path, warnings: list[str]) -> list[dict]:
    apps = []
    for parent_name in APP_PARENTS:
        parent = root / parent_name
        if not parent.is_dir():
            continue
        for bundle in sorted(parent.glob("*.app")):
            info_path = bundle / "Info.plist"
            info = read_plist(info_path, warnings) if info_path.is_file() else None
            bundle_id = info.get("CFBundleIdentifier") if isinstance(info, dict) else None
            if bundle.name.casefold() != "appstore.app" and bundle_id != "com.apple.AppStore":
                continue
            apps.append({
                "path": rel(root, bundle),
                "bundle_id": bundle_id,
                "executable": info.get("CFBundleExecutable") if isinstance(info, dict) else None,
                "info_plist_present": info_path.is_file(),
            })
    return apps


def job_record(label: str, data: dict, location: str) -> dict:
    program = data.get("Program")
    argv = data.get("ProgramArguments")
    if not program and isinstance(argv, list) and argv and isinstance(argv[0], str):
        program = argv[0]
    return {
        "label": label,
        "source": location,
        "program": program if isinstance(program, str) else None,
        "disabled_in_definition": bool(data.get("Disabled", False)),
    }


def find_jobs(root: Path, warnings: list[str]) -> dict[str, list[dict]]:
    jobs: dict[str, list[dict]] = {name: [] for name in SERVICE_HINTS}
    seen = set()

    def record(label, data, source):
        if not isinstance(label, str) or not isinstance(data, dict):
            return
        for hint in SERVICE_HINTS:
            if hint.casefold() not in label.casefold():
                continue
            key = (label, source)
            if key not in seen:
                seen.add(key)
                jobs[hint].append(job_record(label, data, source))

    # These ports use the launchd job cache; other images may have loose jobs.
    launchd_path = root / "System/Library/xpc/launchd.plist"
    if launchd_path.is_file():
        cache = read_plist(launchd_path, warnings)
        if isinstance(cache, dict):
            for group in ("LaunchDaemons", "LaunchAgents", "LaunchAngels"):
                group_data = cache.get(group)
                if not isinstance(group_data, dict):
                    continue
                for key, value in group_data.items():
                    if isinstance(value, dict):
                        record(value.get("Label") or key, value, rel(root, launchd_path) + ":" + group)

    for folder_name in JOB_DIRECTORIES:
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.plist")):
            data = read_plist(path, warnings)
            if isinstance(data, dict):
                record(data.get("Label") or path.stem, data, rel(root, path))
    return jobs


def inventory(root: Path) -> dict:
    warnings: list[str] = []
    apps = find_apps(root, warnings)
    jobs = find_jobs(root, warnings)
    return {
        "root": str(root),
        "app_store_bundles": apps,
        "service_jobs": jobs,
        "service_hints_not_found": [name for name, records in jobs.items() if not records],
        "warnings": warnings,
        "limits": [
            "A missing file here does not prove the IPSW lacks it: check cryptexes and mounts.",
            "A job definition does not prove that the process launches or answers XPC.",
            "This audit cannot verify networking, Apple ID authentication, storefronts, or downloads.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="mounted iOS root directory (read-only is fine)")
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir() or not (root / "System/Library").is_dir():
        parser.error("not an accessible iOS root (System/Library not found)")
    data = inventory(root)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"iOS root: {root}")
        if data["app_store_bundles"]:
            for app in data["app_store_bundles"]:
                print(f"App Store candidate: {app['path']} (bundle={app['bundle_id']})")
        else:
            print("App Store: not found in scanned app paths (not proof of absence)")
        print("Service jobs (found / no matching definition in scanned locations):")
        for hint, records in data["service_jobs"].items():
            print(f"  {hint}: {len(records)}")
            for record in records:
                print(f"    {record['label']} @ {record['source']}")
        for warning in data["warnings"]:
            print(f"Warning: {warning}")
        print("Offline inventory only. Network/login/downloads NOT tested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
