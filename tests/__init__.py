"""Test bootstrap for the flat application modules in app/."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))
