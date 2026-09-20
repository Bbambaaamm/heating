#!/usr/bin/env python3
"""Deploy only audited boiler files; stdlib only, no HA credentials needed.

Run on the HA host. --check is read-only. --apply backs up, validates and
rolls files back on a failed check. A restart is an explicit separate flag.
The Git index, automations.yaml, dashboard storage and OIG are not written.
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

BASELINE_SHA256 = {
    "heating/analysis/heating_analytics.yaml": "7f2b20353a2fc3cbd2390505e146270096589b4e2d96374f0af50f26646b6bec",
    "heating/control/kotel_control.yaml": "08f64fbd14ec463bb3360a5b7769b0d3eb90de1516d1dbc362f48bc325f3f593",
    "heating/control/refactor_mode_schedule_override.yaml": "41840de0cb8a477806dbe4788d40f66d626fae6391a4f793bf2860c2e26eeeb7",
    "heating/core/zone_1p_chodba.yaml": "bfe52d6f97fcdfdd003c02ab76a40bfe09eaaa833358bb3c3e5f6414b30cef3c",
    "heating/core/zone_1p_jidelna.yaml": "1f739222a0d9f4839b4777e5e945187456a11a9a7d7a55629753921fc9fbdb23",
    "heating/core/zone_1p_koupelna.yaml": "8b9c7b797c4c845dec1c6d3836b474ad8efa7e9f492bcc29a57ed79c62681762",
    "heating/core/zone_1p_kuchyn.yaml": "988b1b2a569dfe137b203a26012316df23d8e58d98c88e037baea2bd7b36664a",
    "heating/core/zone_2p_mama.yaml": "cf9033e99f3084c98a5e945c0476a1a7afcc41ae4314916365da36d563bb0e20",
    "heating/core/zone_prizemi_chodba_zachod.yaml": "c3c4aa6ff3931620927fd646d6c9579f5a3699e99f3bebcdd5476dfc44685669",
    "heating/core/zone_prizemi_michal.yaml": "4af166ea40e280a240d065666941d0001d8cd133d0b703e05fd39cf0b739a51f",
    "heating/core/zone_sklep_michal.yaml": "24c57e9d95f64a3426fecb135271a9bef7a6709165a44fa92684bd0dc19de16d",
    "heating/policy/policy_config.yaml": "227cfa60f94e3991a8ef1b0d89b7e6cd899f1cbfc2e02ee0425bde26e9b48e21",
    "heating/schedule/preferences/helpers/schedule_helpers_1p_chodba.yaml": "cdf9369caac1a1338ac5b3ca1c473f94a6bd6708119850500475f1103d9881cd",
    "heating/schedule/preferences/helpers/schedule_helpers_1p_jidelna.yaml": "faaa6483c4914be02de08f2f10e716a3cc590da2df41b71f227551e0ff5383d2",
    "heating/schedule/preferences/helpers/schedule_helpers_1p_koupelna.yaml": "5f5fdee7edd8384d0ed010a2d158a56933fd73dd3ff5cd6e7d48e24cc848f5e6",
    "heating/schedule/preferences/helpers/schedule_helpers_1p_kuchyn.yaml": "d930c850c207c5c4556e51b7486baf68296daa6666daaa3be6e2767d996f563c",
    "heating/schedule/preferences/helpers/schedule_helpers_2p_mama.yaml": "7c700b4eb4bbed190cbf26982009453b505ac4ac4f74f3fc107fb5606e3ac936",
    "heating/schedule/preferences/helpers/schedule_helpers_prizemi_chodba_zachod.yaml": "826667816c0eb2ba35f90bc620ab946b1ae45360d99771fae946da1f47a63939",
    "heating/schedule/preferences/helpers/schedule_helpers_prizemi_michal.yaml": "559b0e6d3fc8faed7b5d7b90d60f78aab76da5d1665bde58d4fd103dfac76d9b",
    "heating/schedule/preferences/helpers/schedule_helpers_sklep_michal.yaml": "250567d50af3a1e5ca453ee4b9edb141cae5b003415f880b25022978cc07e213",
    "heating/ui/controls/mode_controls.yaml": "9dc958ca1776d0b83a0f2054d4e741a1a8a345ab40ec1ae050042ca9bae85969"
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def current(root, path):
    file = root / path
    if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root):
        raise RuntimeError(f"Neplatný soubor nebo odkaz: {file}")
    return file.read_bytes()


def atomic_write(file, data):
    metadata = file.stat()
    fd, temp = tempfile.mkstemp(prefix=".boiler-audit-", dir=file.parent)
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


def restore(root, backup):
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest["config"] != str(root) or set(manifest["files"]) != set(BASELINE_SHA256):
        raise RuntimeError("Záloha patří jiné konfiguraci nebo má jiný seznam souborů.")
    originals = {}
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


def deploy(root, source, apply):
    source = git(root, "rev-parse", "--verify", source + "^{commit}").decode().strip()
    original, target = {}, {}
    for path, expected in BASELINE_SHA256.items():
        original[path] = current(root, path)
        target[path] = git(root, "show", f"{source}:{path}")
        if digest(original[path]) not in [expected, digest(target[path])]:
            raise RuntimeError(f"Neznámá místní úprava: {path}. Nic nebylo zapsáno.")
    print(f"Ověřeno {len(target)} souborů; zdroj {source}.", flush=True)
    if not apply:
        print("Kontrola nic nezměnila. Pro nasazení použij --apply.")
        return
    if all(original[p] == target[p] for p in target):
        print("Soubory již odpovídají opravě. Kontroluji konfiguraci.", flush=True)
        subprocess.run(["ha", "core", "check"], check=True)
        return
    backup_parent = root / "boiler_audit_backups"
    if backup_parent.is_symlink():
        raise RuntimeError("Adresář záloh nesmí být symbolický odkaz.")
    backup_parent.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="audit-", dir=backup_parent))
    manifest = {"config": str(root), "source": source, "files": {}}
    for path in target:
        dest = backup / "files" / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / path, dest)
        if dest.read_bytes() != original[path] or current(root, path) != original[path]:
            raise RuntimeError(f"Soubor se při zálohování změnil: {path}")
        manifest["files"][path] = {"before": digest(original[path]), "after": digest(target[path])}
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Záloha: {backup}", flush=True)
    print(f"Návrat: použij tento skript s --config {root} --rollback {backup}", flush=True)
    changed = []
    try:
        for path, data in target.items():
            if current(root, path) != original[path]:
                raise RuntimeError(f"Souběžná úprava: {path}")
            atomic_write(root / path, data)
            changed.append(path)
        if any(current(root, p) != target[p] for p in target):
            raise RuntimeError("Kontrola zapsaných souborů neprošla.")
        subprocess.run(["ha", "core", "check"], check=True)
    except BaseException:
        # Restore only files this invocation wrote, preserving any concurrent edit.
        for path in changed:
            if current(root, path) != target[path]:
                raise RuntimeError(f"Souběžná změna brání návratu: {path}; záloha {backup}")
        for path in changed:
            atomic_write(root / path, original[path])
        print("Nasazení neprošlo. Zapsané soubory vráceny; HA nerestartován.", flush=True)
        raise
    print("Oprava zapsána a kontrola konfigurace prošla.", flush=True)


def main():
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
    with (root / ".boiler_audit_deploy.lock").open("a") as lock:
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
