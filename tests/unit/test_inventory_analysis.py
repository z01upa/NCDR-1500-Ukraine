from __future__ import annotations

import sys
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from inventory.analyze_inventory import _normalized_region_key


class InventoryComparisonTests(unittest.TestCase):
    def test_regional_database_names_normalize_to_same_family(self) -> None:
        italy = _normalized_region_key(
            "OPEL NCDx Italia 2010-2011\\DB\\IZ.MP0", "OPEL NCDx Italia 2010-2011"
        )
        scandinavia = _normalized_region_key(
            "OPEL NCDx Scandinavia 2010-2011\\DB\\SCZ.MP0", "OPEL NCDx Scandinavia 2010-2011"
        )
        self.assertEqual(italy, scandinavia)
        self.assertEqual(italy, "db\\{region}z.mp0")

    def test_rd_family_normalizes_without_assigning_semantics(self) -> None:
        self.assertEqual(
            _normalized_region_key("OPEL NCDx Italia 2010-2011\\DB\\I.RD", "OPEL NCDx Italia 2010-2011"),
            _normalized_region_key("OPEL NCDx Scandinavia 2010-2011\\DB\\SC.RD", "OPEL NCDx Scandinavia 2010-2011"),
        )


if __name__ == "__main__":
    unittest.main()
