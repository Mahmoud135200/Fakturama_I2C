"""Shared test setup: puts src/ on sys.path so the tests import the package
without requiring an editable install."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
