import csv, hashlib, json, tempfile, unittest, zipfile
from pathlib import Path
from research.db_lab.artifact_lab.db_validation import validate_db0
from research.db_lab.artifact_lab.db0_diff import compare_db0,group_identical_experiments
from research.db_lab.tasks import package_run

def fake_db(change_sector=None,change=0):
    data=bytearray(18*512)
    for sec in range(2,18):
        off=sec*512
        data[off:off+3]=sec.to_bytes(3,"big"); data[off+3:off+8]=bytes((1,0,1,0,0))
        data[off+8:off+512]=bytes([0x30+change if sec==change_sector else 0x30])*(512-8)
    return bytes(data)

class FoundationTests(unittest.TestCase):
    def test_structural_db0_rejects_signature_only_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            valid=Path(td)/"DB_0"; valid.write_bytes(fake_db())
            self.assertTrue(validate_db0(valid)["valid"])
            for name in (".DS_Store","CARINET"):
                p=Path(td)/name; p.write_bytes(b"\0\0\0"+b"x"*(4096-3))
                result=validate_db0(p); self.assertTrue(result["signature_hit"]); self.assertFalse(result["valid"])

    def test_complete_record_diff_and_identical_hash_grouping(self):
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/"a"; b=Path(td)/"b"; a.write_bytes(fake_db()); b.write_bytes(fake_db(9,1))
            va=validate_db0(a); vb=validate_db0(b)
            va["path"]=str(a); vb["path"]=str(b)
            out=compare_db0(None,va,vb,"OUTPUT_B")
            self.assertEqual(out["records_changed"],1)
            self.assertEqual(out["original_record_count"],16)
            self.assertEqual(out["details"][0]["sector"],9)
            self.assertEqual(out["details"][0]["first_physical_change"],9*512+8)
            self.assertTrue(json.loads(out["details"][0]["physical_changed_ranges"]))
            rows=[{"experiment":"OUTPUT_A","experiment_db_sha256":"abc"},{"experiment":"OUTPUT_E","experiment_db_sha256":"abc"}]
            groups=group_identical_experiments(rows)
            self.assertEqual(groups,{"abc":["OUTPUT_A","OUTPUT_E"]})

    def test_package_manifest_verifies_member_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name,body in (("TASK.md","task"),("task.json","{}"),("run.json",json.dumps({"task_id":"T","run_id":"R"})),("environment.json","{}"),("REPORT.md","report"),("REPORT.html","<h1>r</h1>"),("CHATGPT_SUMMARY.txt","summary")):(root/name).write_text(body)
            (root/"data").mkdir(); large=root/"data"/"required-large.csv"; large.write_bytes(b"x"*(5*1024*1024))
            required=["TASK.md","task.json","run.json","REPORT.md","CHATGPT_SUMMARY.txt","PACKAGE_MANIFEST.json","data/required-large.csv"]
            result=package_run(root,required)
            self.assertEqual(result["status"],"READY")
            with zipfile.ZipFile(result["path"]) as z:
                manifest=json.loads(z.read("PACKAGE_MANIFEST.json"))
                self.assertEqual(len(manifest["members"]),8)
                for item in manifest["members"]: self.assertEqual(hashlib.sha256(z.read(item["path"])).hexdigest(),item["sha256"])

if __name__=="__main__": unittest.main()
