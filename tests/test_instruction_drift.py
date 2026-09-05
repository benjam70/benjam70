import subprocess
import sys
import unittest
from pathlib import Path


class InstructionDriftTests(unittest.TestCase):
    def test_instruction_drift_check_passes(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "tools/check_instruction_drift.py"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
