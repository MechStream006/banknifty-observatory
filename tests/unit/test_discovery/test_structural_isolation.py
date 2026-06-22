"""
Structural enforcement: lib.discovery must not be imported by production modules.

This test scans every production directory for any Python source file that
imports from lib.discovery, and fails the build if any are found.

Permitted callers: scripts/, tests/ only.

Production directories protected:
    acquisition/, derivation/, research/, persistence/, integrity/, curation/

lib/ sibling modules protected (config, logging, db, metrics, etc.):
    Any file under lib/ outside lib/discovery/ itself.
"""
from __future__ import annotations

import pathlib

_EXCLUDED_DIR_PARTS: frozenset[str] = frozenset(
    {"future", ".venv", "venv", "__pycache__", ".git"}
)


def _project_root() -> pathlib.Path:
    # This file lives at tests/unit/test_discovery/test_structural_isolation.py
    # parents[0] = tests/unit/test_discovery
    # parents[1] = tests/unit
    # parents[2] = tests
    # parents[3] = banknifty-observatory  (project root)
    return pathlib.Path(__file__).parents[3]


def _contains_discovery_import(source: str) -> bool:
    """Return True if source contains any import of lib.discovery."""
    return "lib.discovery" in source or "from lib.discovery" in source


class TestDiscoveryIsolation:
    def test_no_lib_discovery_import_in_production_dirs(self) -> None:
        """acquisition/, derivation/, research/, persistence/, integrity/,
        curation/ must not import lib.discovery."""
        root = _project_root()
        production_dirs = (
            "acquisition",
            "derivation",
            "research",
            "persistence",
            "integrity",
            "curation",
        )
        violations: list[str] = []

        for dir_name in production_dirs:
            scan_root = root / dir_name
            if not scan_root.exists():
                continue
            for py_file in scan_root.rglob("*.py"):
                if any(part in _EXCLUDED_DIR_PARTS for part in py_file.parts):
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if _contains_discovery_import(source):
                    violations.append(str(py_file.relative_to(root)))

        assert violations == [], (
            "lib.discovery imported in production code.\n"
            "lib.discovery is restricted to scripts/ and tests/ only.\n"
            "Violations:\n" + "\n".join(f"  {v}" for v in violations)
        )

    def test_no_lib_discovery_import_in_lib_siblings(self) -> None:
        """lib/ production modules (config, logging, db, metrics, etc.)
        must not import lib.discovery. lib/discovery/ itself is exempt."""
        root = _project_root()
        lib_root = root / "lib"
        discovery_pkg = lib_root / "discovery"

        violations: list[str] = []

        for py_file in lib_root.rglob("*.py"):
            if any(part in _EXCLUDED_DIR_PARTS for part in py_file.parts):
                continue
            # Exempt lib/discovery/ itself — it is allowed to contain
            # references to its own fully-qualified path.
            try:
                py_file.relative_to(discovery_pkg)
                continue
            except ValueError:
                pass

            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if _contains_discovery_import(source):
                violations.append(str(py_file.relative_to(root)))

        assert violations == [], (
            "lib.discovery imported from within lib/ production modules.\n"
            "These modules must not depend on the discovery subsystem.\n"
            "Violations:\n" + "\n".join(f"  {v}" for v in violations)
        )

    def test_discovery_module_itself_is_importable(self) -> None:
        """Confirm lib.discovery is a valid Python package (not future-sealed
        in the traditional sense — it is importable, just isolated)."""
        import lib.discovery  # noqa: F401
        assert lib.discovery.__doc__ is not None

    def test_discovery_errors_importable(self) -> None:
        from lib.discovery._errors import BNODiscoveryError
        assert issubclass(BNODiscoveryError, Exception)

    def test_discovery_models_importable(self) -> None:
        from lib.discovery._models import PollRecord
        assert PollRecord.__dataclass_params__ is not None  # type: ignore[attr-defined]
