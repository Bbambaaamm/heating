"""Recovery tests: no HA instance, network or real heating commands."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("boiler_deploy", Path(__file__).resolve().parents[1] / "scripts/deploy_boiler_audit.py")
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


class BoilerDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before = {"heating/a.yaml": b"value: old-a\n", "heating/b.yaml": b"value: old-b\n"}
        self.after = {p: value.replace(b"old-", b"new-") for p, value in self.before.items()}
        for p, value in self.before.items():
            (self.root / p).parent.mkdir(exist_ok=True)
            (self.root / p).write_bytes(value)
        (self.root / "automations.yaml").write_bytes(b"local: preserved\n")
        def git(root, *args):
            return b"f" * 40 if args[0] == "rev-parse" else self.after[args[-1].split(":", 1)[1]]
        self.addCleanup(patch.stopall)
        patch.object(DEPLOY, "BASELINE_SHA256", {p: DEPLOY.digest(b) for p, b in self.before.items()}).start()
        patch.object(DEPLOY, "git", side_effect=git).start()
        self.run = patch.object(DEPLOY.subprocess, "run").start()

    def test_check_is_read_only(self):
        DEPLOY.deploy(self.root, "f" * 40, False)
        self.assertFalse((self.root / "boiler_audit_backups").exists())
        self.run.assert_not_called()
        for p, data in self.before.items():
            self.assertEqual((self.root / p).read_bytes(), data)

    def test_apply_backs_up_and_explicit_rollback_restores_original(self):
        DEPLOY.deploy(self.root, "f" * 40, True)
        self.run.assert_called_once_with(["ha", "core", "check"], check=True)
        backup = next((self.root / "boiler_audit_backups").iterdir())
        for p, data in self.after.items():
            self.assertEqual((self.root / p).read_bytes(), data)
            self.assertEqual((backup / "files" / p).read_bytes(), self.before[p])
        self.assertEqual((self.root / "automations.yaml").read_bytes(), b"local: preserved\n")
        DEPLOY.restore(self.root, backup)
        for p, data in self.before.items():
            self.assertEqual((self.root / p).read_bytes(), data)

    def test_unknown_local_edit_aborts_before_any_write(self):
        (self.root / "heating/b.yaml").write_bytes(b"local: do not overwrite\n")
        with self.assertRaisesRegex(RuntimeError, "Neznámá místní úprava"):
            DEPLOY.deploy(self.root, "f" * 40, True)
        self.assertFalse((self.root / "boiler_audit_backups").exists())
        self.assertEqual((self.root / "heating/a.yaml").read_bytes(), self.before["heating/a.yaml"])
        self.run.assert_not_called()

    def test_failed_ha_check_restores_all_written_files(self):
        self.run.side_effect = subprocess.CalledProcessError(1, ["ha", "core", "check"])
        with self.assertRaises(subprocess.CalledProcessError):
            DEPLOY.deploy(self.root, "f" * 40, True)
        for p, data in self.before.items():
            self.assertEqual((self.root / p).read_bytes(), data)
        self.run.assert_called_once_with(["ha", "core", "check"], check=True)

    def test_rollback_does_not_erase_later_edit(self):
        DEPLOY.deploy(self.root, "f" * 40, True)
        backup = next((self.root / "boiler_audit_backups").iterdir())
        (self.root / "heating/b.yaml").write_bytes(b"later: preserved\n")
        with self.assertRaisesRegex(RuntimeError, "Pozdější místní změna"):
            DEPLOY.restore(self.root, backup)
        self.assertEqual((self.root / "heating/a.yaml").read_bytes(), self.after["heating/a.yaml"])
        self.assertEqual((self.root / "heating/b.yaml").read_bytes(), b"later: preserved\n")


if __name__ == "__main__":
    unittest.main()
