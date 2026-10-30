import tempfile, unittest
from pathlib import Path
from research.db_lab.artifact_lab.catalog import ArtifactCatalog
from research.db_lab.project_summary import build_project_summary
from research.db_lab.tasks import implementation_status

class ProjectSummaryTests(unittest.TestCase):
    def test_task_implementation_status_is_three_state(self):
        self.assertEqual(implementation_status(["project_inventory"]),"SUPPORTED")
        self.assertEqual(implementation_status(["project_inventory","missing_module"]),"PARTIAL")
        self.assertEqual(implementation_status(["missing_module"]),"UNSUPPORTED")

    def test_overview_counts_match_authoritative_catalog_queries(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"OUTPUT_A").mkdir(); cat=ArtifactCatalog(root)
            a=cat._artifact(root/"OUTPUT_A","controlled_experiment",size=0,sha="a",magic="",state="CATALOGUED")
            cat._insert_file(a,root/"OUTPUT_A"/"DB/DB_0","DB/DB_0",512,"db","db0","",0,classification={"artifact_role":"navigation_database","format_candidate":"DB_0","validated_format":"DB_0","validation_status":"VALIDATED_DB_0"})
            cat._insert_file(a,root/"OUTPUT_A"/"DB/.DS_Store","DB/.DS_Store",512,"ds","db0_candidate","",0,classification={"artifact_role":"generic_file","format_candidate":"DB_0","validation_status":"REJECTED_DB_0_CANDIDATE"})
            cat.db.commit(); cat.close()
            model=build_project_summary(root)
            db=ArtifactCatalog(root)
            expected={"artifacts":db.db.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts GROUP BY source_path)").fetchone()[0],"files":db.db.execute("SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE COALESCE(is_directory,0)=0 GROUP BY source_path,relative_path)").fetchone()[0],"validated_db0":db.db.execute("SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE is_directory=0 AND validated_format='DB_0' GROUP BY source_path,relative_path)").fetchone()[0],"controlled_experiment_sets":db.db.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts WHERE source_type='controlled_experiment' AND (filename='ORIGINAL' OR filename LIKE 'OUTPUT_%') GROUP BY source_path)").fetchone()[0],"disc_images":db.db.execute("SELECT COUNT(*) FROM (SELECT a.source_path FROM artifacts a JOIN disc_images d USING(artifact_id) WHERE d.status IN ('READABLE','VALIDATED','OK') GROUP BY a.source_path)").fetchone()[0],"research_runs":db.db.execute("SELECT COUNT(*) FROM run_tasks").fetchone()[0],"open_tasks":db.db.execute("SELECT COUNT(*) FROM task_queue WHERE status IN ('QUEUED','RUNNING','BLOCKED')").fetchone()[0]}
            for key,value in expected.items(): self.assertEqual(model["counts"][key],value,key)
            self.assertEqual(model["counts"]["validated_db0"],1)
            db.close()

if __name__=="__main__": unittest.main()
