from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


APP_NAME = "RM SNI Spoofer"
PROJECT_ROOT = Path(__file__).resolve().parent
ENTRYPOINT = PROJECT_ROOT / "main.py"
RUNTIME_FILES = ["config.json"]
OPTIONAL_RUNTIME_FILES = []
RUNTIME_DIRECTORIES = ["xray"]
APP_ICON_PATH = PROJECT_ROOT / "logo.ico"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the bundled Windows distribution and stage runtime files beside the exe.",
    )
    parser.add_argument(
        "--dist-dir",
        default="dist",
        help="Output directory for the built application bundle.",
    )
    parser.add_argument(
        "--build-dir",
        default="build",
        help="Working directory used by PyInstaller.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the build and staging steps without executing them.",
    )
    parser.add_argument(
        "--zip-file",
        help="Optional path to a zip archive created from the contents of the built bundle.",
    )
    parser.add_argument(
        "--force-connect-port",
        action="store_true",
        help="Stage the bundled config so runtime always uses CONNECT_PORT and ignores the active share URL port.",
    )
    return parser.parse_args()


def print_command(command: list[str]) -> None:
    print(subprocess.list2cmdline(command))


def run_command(command: list[str], *, dry_run: bool) -> None:
    print_command(command)
    if dry_run:
        return
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def remove_path(path: Path, *, dry_run: bool) -> None:
    if not path.exists():
        return
    print(f"remove {path}")
    if dry_run:
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def copy_file(source: Path, destination: Path, *, dry_run: bool) -> None:
    print(f"copy {source} -> {destination}")
    if dry_run:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_directory(source: Path, destination: Path, *, dry_run: bool) -> None:
    print(f"copytree {source} -> {destination}")
    if dry_run:
        return
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def write_bundle_config(bundle_dir: Path, *, force_connect_port: bool, dry_run: bool) -> None:
    source_path = PROJECT_ROOT / "config.json"
    destination_path = bundle_dir / "config.json"
    print(f"copy {source_path} -> {destination_path}")
    if dry_run:
        return

    with source_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")

    if force_connect_port:
        config["FORCE_CONNECT_PORT"] = True

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with destination_path.open("w", encoding="utf-8", newline="\n") as config_file:
        json.dump(config, config_file, ensure_ascii=True, indent=2)
        config_file.write("\n")


def require_paths() -> None:
    if not ENTRYPOINT.is_file():
        raise FileNotFoundError(f"entrypoint not found: {ENTRYPOINT}")
    if not APP_ICON_PATH.is_file():
        raise FileNotFoundError(f"app icon not found: {APP_ICON_PATH}")
    for file_name in RUNTIME_FILES:
        file_path = PROJECT_ROOT / file_name
        if not file_path.is_file():
            raise FileNotFoundError(f"required runtime file not found: {file_path}")
    for directory_name in RUNTIME_DIRECTORIES:
        directory_path = PROJECT_ROOT / directory_name
        if not directory_path.is_dir():
            raise FileNotFoundError(f"required runtime directory not found: {directory_path}")


def stage_runtime_files(bundle_dir: Path, *, force_connect_port: bool, dry_run: bool) -> None:
    for file_name in RUNTIME_FILES:
        if file_name == "config.json":
            write_bundle_config(
                bundle_dir,
                force_connect_port=force_connect_port,
                dry_run=dry_run,
            )
            continue
        copy_file(PROJECT_ROOT / file_name, bundle_dir / file_name, dry_run=dry_run)
    for file_name in OPTIONAL_RUNTIME_FILES:
        file_path = PROJECT_ROOT / file_name
        if file_path.is_file():
            copy_file(file_path, bundle_dir / file_name, dry_run=dry_run)
    for directory_name in RUNTIME_DIRECTORIES:
        copy_directory(PROJECT_ROOT / directory_name, bundle_dir / directory_name, dry_run=dry_run)


def create_bundle_zip(bundle_dir: Path, zip_path: Path, *, dry_run: bool) -> None:
    print(f"zip {bundle_dir} -> {zip_path}")
    if dry_run:
        return
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_dir():
                continue
            archive.write(path, path.relative_to(bundle_dir))


def build_bundle(dist_dir: Path, build_dir: Path, *, force_connect_port: bool, dry_run: bool) -> None:
    spec_dir = build_dir / "spec"
    pyinstaller_work_dir = build_dir / "pyinstaller"
    bundle_dir = dist_dir / APP_NAME

    remove_path(bundle_dir, dry_run=dry_run)
    remove_path(spec_dir, dry_run=dry_run)
    remove_path(pyinstaller_work_dir, dry_run=dry_run)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--hidden-import",
        "gui",
        "--icon",
        str(APP_ICON_PATH),
        "--name",
        APP_NAME,
        "--distpath",
        str(bundle_dir),
        "--workpath",
        str(pyinstaller_work_dir),
        "--specpath",
        str(spec_dir),
        str(ENTRYPOINT),
    ]
    run_command(command, dry_run=dry_run)
    stage_runtime_files(
        bundle_dir,
        force_connect_port=force_connect_port,
        dry_run=dry_run,
    )


def main() -> int:
    args = parse_args()
    require_paths()
    dist_dir = (PROJECT_ROOT / args.dist_dir).resolve()
    build_dir = (PROJECT_ROOT / args.build_dir).resolve()
    build_bundle(
        dist_dir,
        build_dir,
        force_connect_port=args.force_connect_port,
        dry_run=args.dry_run,
    )
    bundle_dir = dist_dir / APP_NAME
    if args.zip_file:
        zip_path = Path(args.zip_file)
        if not zip_path.is_absolute():
            zip_path = PROJECT_ROOT / zip_path
        create_bundle_zip(bundle_dir, zip_path.resolve(), dry_run=args.dry_run)
        print(f"Release zip ready at {zip_path.resolve()}")
    print(f"Build bundle ready at {bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())