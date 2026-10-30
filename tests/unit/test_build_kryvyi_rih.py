from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.osm import build_kryvyi_rih


class BuildKryvyiRihTests(unittest.TestCase):
    def test_versioned_overpass_snapshot_is_imported_without_clobber(self) -> None:
        osm = '''<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="47.9000" lon="33.4000" />
  <node id="2" lat="47.9010" lon="33.4010" />
  <way id="10">
    <nd ref="1" /><nd ref="2" />
    <tag k="highway" v="residential" />
    <tag k="name:uk" v="Тестова вулиця" />
  </way>
</osm>
'''.encode("utf-8")
        work_dir = Path(__file__).resolve().parents[2] / "work"
        with tempfile.TemporaryDirectory(dir=work_dir) as folder:
            data_dir = Path(folder) / "osm"
            data_dir.mkdir()

            def write_fake_download(*, output_path: Path | None = None, **_kwargs: object) -> dict[str, object]:
                assert output_path is not None
                output_path.write_bytes(osm)
                return {"status": "DOWNLOADED", "path": str(output_path),
                        "bytes": len(osm), "sha256": "fixture"}

            with patch.object(build_kryvyi_rih, "DATA_DIR", data_dir), \
                 patch.object(build_kryvyi_rih, "download_overpass", side_effect=write_fake_download):
                result = build_kryvyi_rih.build("overpass", output_prefix="city_fixture")
                database = data_dir / "city_fixture.sqlite"
                metadata = data_dir / "city_fixture.json"

                self.assertTrue(database.is_file())
                self.assertTrue(metadata.is_file())
                self.assertEqual(result["import_summary"]["routable_way_count"], 1)
                self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["source_sha256"],
                                 result["source_sha256"])
                before = database.read_bytes()
                with self.assertRaises(FileExistsError):
                    build_kryvyi_rih.build("overpass", output_prefix="city_fixture")
                self.assertEqual(database.read_bytes(), before)

    def test_versioned_prefix_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            build_kryvyi_rih.build("overpass", output_prefix="..\\outside")


if __name__ == "__main__":
    unittest.main()
