"""Double-click launcher for the standalone personal POI editor."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.poi_editor import main


if __name__ == "__main__":
    raise SystemExit(main())
