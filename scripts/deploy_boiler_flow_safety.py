#!/usr/bin/env python3
"""Deploy only the audited boiler-flow safety files; stdlib only.

Run on the Home Assistant host. ``--check`` is read-only. ``--apply``
creates a verified backup, writes atomically, runs ``ha core check`` and
rolls every written file back if validation fails. Restart is explicit.

The accepted baseline is commit a04f9fe, which is the revision deployed
before this fix. Git index, automations.yaml, dashboard storage and OIG
files are never written.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


BASELINE_COMMIT = "a04f9fee9f6671283164add761cfecedf881c2b9"

BASELINE_SHA256 = {
    "blueprints/automation/heating/smart_zone_schedule.yaml":
        "4320b9fc3e002dc292fc455e7ffff484c41e0245147f6429d78a63e7fac290ef",
    "heating/control/kotel_control.yaml":
        "137ac6d03242e456e9cb1604e0e26664a66cc1946f3f82d7a8963ed90e1623fd",
    "heating/control/reliability_failsafe.yaml":
        "2f2e68bf1b4f41c44640aa819d6abb91f7edd7f59bd089a1007cc66c2c948041",
    "heating/policy/policy_config.yaml":
        "81fc78dca2226fa8d7080d882bbb058ac67aecc72a3478b5c79782db0ddf43ae",
    "heating/policy/policy_effective.yaml":
        "f834cf367800bece5585f849fdb500095a0b200df0ada4bc7f67b34119d1e8e5",
}

BACKUP_DIRECTORY = "boiler_flow_safety_backups"
LOCK_FILE = ".boiler_flow_safety_deploy.lock"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def current(root: Path, path: str) -> bytes:
    file = root / path
    if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root):
        raise RuntimeError(f"Neplatný soubor nebo odkaz: {file}")
    return file.read_bytes()


def atomic_write(file: Path, data: bytes) -> None:
    metadata = file.stat()
    fd, temp = tempfile.mkstemp(prefix=".boiler-flow-safety-", dir=file.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
            os.fchmod(out.fileno(), metadata.st_mode & 0o777)
            os.fchown(out.fileno(), metadata.st_uid, metadata.st_gid)
        os.replace(temp, file)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def restore(root: Path, backup: Path) -> None:
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest["config"] != str(root) or set(manifest["files"]) != set(BASELINE_SHA256):
        raise RuntimeError("Záloha patří jiné konfiguraci nebo má jiný seznam souborů.")

    originals: dict[str, bytes] = {}
    for path, hashes in manifest["files"].items():
        original = (backup / "files" / path).read_bytes()
        if digest(original) != hashes["before"]:
            raise RuntimeError(f"Poškozená záloha: {path}")
        if digest(current(root, path)) not in [hashes["before"], hashes["after"]]:
            raise RuntimeError(f"Pozdější místní změna; automatický návrat odmítnut: {path}")
        originals[path] = original

    for path, original in originals.items():
        atomic_write(root / path, original)
    print("Původní soubory obnoveny.", flush=True)


def deploy(root: Path, source: str, apply: bool) -> None:
    source = git(root, "rev-parse", "--verify", source + "^{commit}").decode().strip()
    original: dict[str, bytes] = {}
    target: dict[str, bytes] = {}

    for path, expected in BASELINE_SHA256.items():
        original[path] = current(root, path)
        target[path] = git(root, "show", f"{source}:{path}")
        if digest(original[path]) not in [expected, digest(target[path])]:
            raise RuntimeError(f"Neznámá místní úprava: {path}. Nic nebylo zapsáno.")

    print(f"Ověřeno {len(target)} souborů; zdroj {source}.", flush=True)
    if not apply:
        print("Kontrola nic nezměnila. Pro nasazení použij --apply.")
        return

    if all(original[path] == target[path] for path in target):
        print("Soubory již odpovídají opravě. Kontroluji konfiguraci.", flush=True)
        subprocess.run(["ha", "core", "check"], check=True)
        return

    backup_parent = root / BACKUP_DIRECTORY
    if backup_parent.is_symlink():
        raise RuntimeError("Adresář záloh nesmí být symbolický odkaz.")
    backup_parent.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="flow-", dir=backup_parent))
    manifest = {"config": str(root), "source": source, "files": {}}

    for path in target:
        destination = backup / "files" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / path, destination)
        if destination.read_bytes() != original[path] or current(root, path) != original[path]:
            raise RuntimeError(f"Soubor se při zálohování změnil: {path}")
        manifest["files"][path] = {
            "before": digest(original[path]),
            "after": digest(target[path]),
        }

    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Záloha: {backup}", flush=True)
    print(
        f"Návrat: použij tento skript s --config {root} --rollback {backup}",
        flush=True,
    )

    changed: list[str] = []
    try:
        for path, data in target.items():
            if current(root, path) != original[path]:
                raise RuntimeError(f"Souběžná úprava: {path}")
            atomic_write(root / path, data)
            changed.append(path)
        if any(current(root, path) != target[path] for path in target):
            raise RuntimeError("Kontrola zapsaných souborů neprošla.")
        subprocess.run(["ha", "core", "check"], check=True)
    except BaseException:
        for path in changed:
            if current(root, path) != target[path]:
                raise RuntimeError(f"Souběžná změna brání návratu: {path}; záloha {backup}")
        for path in changed:
            atomic_write(root / path, original[path])
        print("Nasazení neprošlo. Zapsané soubory vráceny; HA nerestartován.", flush=True)
        raise

    print("Oprava zapsána a kontrola konfigurace prošla.", flush=True)
    print("Home Assistant nebyl restartován. Servisní režim ponech zapnutý.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/config")
    parser.add_argument("--source")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", type=Path)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()

    if args.check and args.restart:
        parser.error("--check nelze kombinovat s --restart")
    if not args.rollback and not args.source:
        parser.error("--source musí být konkrétní ověřený commit")

    root = Path(args.config).resolve()
    if args.check:
        deploy(root, args.source, False)
        return

    with (root / LOCK_FILE).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.rollback:
            restore(root, args.rollback.resolve())
            subprocess.run(["ha", "core", "check"], check=True)
        else:
            deploy(root, args.source, True)
        if args.restart:
            print("Restartuji Home Assistant.", flush=True)
            subprocess.run(["ha", "core", "restart"], check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"STOP: {exc}") from exc
