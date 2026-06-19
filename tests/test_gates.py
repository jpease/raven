import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from raven_lib.gates import GateSpec, gate_spec_for, load_gate_specs


class GatesTests(unittest.TestCase):
    def test_python_gate_spec_present(self):
        specs = load_gate_specs()
        self.assertIn("python", specs)
        spec = specs["python"]
        self.assertIsInstance(spec, GateSpec)

    def test_python_recipes_match_justfile(self):
        spec = gate_spec_for("python")
        assert spec is not None
        for recipe in ("lint", "format", "typecheck", "test"):
            self.assertIn(recipe, spec.recipes)

    def test_python_detect_signals_include_pyproject(self):
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertIn("pyproject.toml", spec.detect_signals)

    def test_python_fallback_for_lint_is_ruff(self):
        spec = gate_spec_for("python")
        assert spec is not None
        self.assertEqual(spec.fallback_commands["lint"], ("ruff", "check", "."))

    def test_unknown_template_returns_none(self):
        self.assertIsNone(gate_spec_for("cobol"))


if __name__ == "__main__":
    unittest.main()
