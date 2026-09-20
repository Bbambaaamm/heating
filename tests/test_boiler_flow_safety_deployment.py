"""Recovery tests for the narrow boiler-flow deployment helper."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "boiler_flow_deploy", ROOT / "scripts/deploy_boiler_flow_safety.py"
)
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


class BoilerFlowDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before = {
            "heating/a.yaml": b"value: old-a\n",
            "heating/b.yaml": b"value: old-b\n",
        }
        self.after = {
            path: value.replace(b"old-", b"new-")
            for path, value in self.before.items()
        }
        for path, value in self.before.items():
            (self.root / path).parent.mkdir(exist_ok=True)
            (self.root / path).write_bytes(value)
        (self.root / "automations.yaml").write_bytes(b"local: preserved\n")

        def git(_root, *args):
            if args[0] == "rev-parse":
                return b"f" * 40
            return self.after[args[-1].split(":", 1)[1]]

        self.addCleanup(patch.stopall)
        patch.object(
            DEPLOY,
            "BASELINE_SHA256",
            {path: DEPLOY.digest(data) for path, data in self.before.items()},
        ).start()
        patch.object(DEPLOY, "git", side_effect=git).start()
        self.run = patch.object(DEPLOY.subprocess, "run").start()

    def backup(self):
        return next((self.root / DEPLOY.BACKUP_DIRECTORY).iterdir())

    def test_check_is_read_only(self):
        DEPLOY.deploy(self.root, "f" * 40, False)
        self.assertFalse((self.root / DEPLOY.BACKUP_DIRECTORY).exists())
        self.run.assert_not_called()
        for path, data in self.before.items():
            self.assertEqual((self.root / path).read_bytes(), data)

    def test_apply_backs_up_and_explicit_rollback_restores_original(self):
        DEPLOY.deploy(self.root, "f" * 40, True)
        self.run.assert_called_once_with(["ha", "core", "check"], check=True)
        backup = self.backup()
        for path, data in self.after.items():
            self.assertEqual((self.root / path).read_bytes(), data)
            self.assertEqual((backup / "files" / path).read_bytes(), self.before[path])
        self.assertEqual((self.root / "automations.yaml").read_bytes(), b"local: preserved\n")
        DEPLOY.restore(self.root, backup)
        for path, data in self.before.items():
            self.assertEqual((self.root / path).read_bytes(), data)

    def test_unknown_local_edit_aborts_before_any_write(self):
        (self.root / "heating/b.yaml").write_bytes(b"local: do not overwrite\n")
        with self.assertRaisesRegex(RuntimeError, "Neznámá místní úprava"):
            DEPLOY.deploy(self.root, "f" * 40, True)
        self.assertFalse((self.root / DEPLOY.BACKUP_DIRECTORY).exists())
        self.assertEqual((self.root / "heating/a.yaml").read_bytes(), self.before["heating/a.yaml"])
        self.run.assert_not_called()

    def test_failed_ha_check_restores_all_written_files(self):
        self.run.side_effect = subprocess.CalledProcessError(1, ["ha", "core", "check"])
        with self.assertRaises(subprocess.CalledProcessError):
            DEPLOY.deploy(self.root, "f" * 40, True)
        for path, data in self.before.items():
            self.assertEqual((self.root / path).read_bytes(), data)
        self.run.assert_called_once_with(["ha", "core", "check"], check=True)

    def test_rollback_does_not_erase_later_edit(self):
        DEPLOY.deploy(self.root, "f" * 40, True)
        backup = self.backup()
        (self.root / "heating/b.yaml").write_bytes(b"later: preserved\n")
        with self.assertRaisesRegex(RuntimeError, "Pozdější místní změna"):
            DEPLOY.restore(self.root, backup)
        self.assertEqual((self.root / "heating/a.yaml").read_bytes(), self.after["heating/a.yaml"])
        self.assertEqual((self.root / "heating/b.yaml").read_bytes(), b"later: preserved\n")


class BoilerFlowBaselineTests(unittest.TestCase):
    def test_declared_baseline_is_exact_deployed_parent(self):
        for path, expected in DEPLOY.BASELINE_SHA256.items():
            data = subprocess.check_output(["git", "-C", str(ROOT), "show", f"a04f9fe:{path}"])
            self.assertEqual(DEPLOY.digest(data), expected, path)


if __name__ == "__main__":
    unittest.main()
