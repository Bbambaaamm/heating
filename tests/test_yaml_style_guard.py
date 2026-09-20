"""Run the YAML guard against real automation snippets."""
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_yaml_and_ha_style.py"
SPEC = importlib.util.spec_from_file_location("service_mode_style_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class YamlStyleGuardTests(unittest.TestCase):
    def check_automation(self, content):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "automations.yaml").write_text(content, encoding="utf-8")
            output = io.StringIO()
            with patch.object(guard, "ROOT", root), redirect_stdout(output):
                result = guard.main()
            return result, output.getvalue()

    def test_accepts_stop_actions_service_data(self):
        result, output = self.check_automation("""- id: one_shot
  trigger:
    - trigger: time
      at: '19:45:00'
  action:
    - action: automation.turn_off
      target:
        entity_id: automation.one_shot
      data:
        stop_actions: false
""")
        self.assertEqual(result, 0, output)

    def test_still_rejects_plural_automation_keys(self):
        for plural, singular in (("triggers", "trigger"), ("actions", "action")):
            with self.subTest(key=plural):
                content = "- id: example\n  trigger: []\n  action: []\n"
                result, output = self.check_automation(content.replace(f"  {singular}:", f"  {plural}:"))
                self.assertEqual(result, 1, output)
                self.assertIn("trigger/action", output)
