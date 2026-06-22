"""
Structural test: os.environ must not be accessed directly outside lib/config/.

This test scans the repository source tree and fails if any .py file outside
lib/config/ references os.environ. It enforces the architectural rule that
all configuration flows through lib.config.get_settings().
"""
from __future__ import annotations

import pathlib


class TestDirectEnvAccessForbidden:
    def test_no_os_environ_outside_lib_config(self) -> None:
        root = pathlib.Path(__file__).parents[4]  # banknifty-observatory/

        # lib/config/ is the only approved place for os.environ access.
        exempt = root / "lib" / "config"

        # Directories excluded from the scan.
        excluded_dir_parts = {
            "future",   # sealed, not active code
            ".venv",
            "venv",
            "__pycache__",
            ".git",
        }

        violations: list[str] = []

        for py_file in root.rglob("*.py"):
            # Skip the exempt lib/config/ directory.
            try:
                py_file.relative_to(exempt)
                continue
            except ValueError:
                pass

            # Skip excluded directories.
            if any(part in excluded_dir_parts for part in py_file.parts):
                continue

            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if "os.environ" in source:
                violations.append(str(py_file.relative_to(root)))

        assert violations == [], (
            "Direct os.environ access found outside lib/config/.\n"
            "Use lib.config.get_settings() instead.\n"
            f"Violations:\n" + "\n".join(f"  {v}" for v in violations)
        )
