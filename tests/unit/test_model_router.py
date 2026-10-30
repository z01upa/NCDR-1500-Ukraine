from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.model_router import ModelRouter


SCHEMA = {
    "type": "object",
    "required": ["decision"],
    "additionalProperties": False,
    "properties": {"decision": {"type": "string", "enum": ["continue", "wait"]}},
}
VALID = json.dumps({"decision": "continue"})


class ModelRouterTests(unittest.TestCase):
    def _router(self, root: Path, quotas: dict[str, int] | None = None) -> ModelRouter:
        return ModelRouter(db_path=root / "router.sqlite", quota_per_model=quotas or {},
                           mutex_name=f"Local\\NCDR-ModelRouter-{uuid.uuid4().hex}")

    def test_schema_validation_and_original_evidence_preservation(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            router = self._router(root, {"qwen3.5:4b": 2})
            evidence = {"source_sha256": "a" * 64, "facts": ["read-only"]}
            original = json.loads(json.dumps(evidence))
            received = []

            result = router.generate_json(
                task_id="A10-SCHEMA", prompt="Return a decision.", schema=SCHEMA,
                models=["qwen3.5:4b"], invoke=lambda model, prompt, schema: received.append((model, schema)) or VALID,
                original_evidence=evidence, retry_limit=0)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["value"], {"decision": "continue"})
        self.assertEqual(result["model"], "qwen3.5:4b")
        self.assertEqual(result["original_evidence"], original)
        self.assertEqual(len(result["original_evidence_sha256"]), 64)
        self.assertEqual(received, [("qwen3.5:4b", SCHEMA)])

    def test_schema_validation_works_without_optional_jsonschema_package(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            router = self._router(Path(temporary), {"qwen3.5:4b": 1})
            with patch.dict(sys.modules, {"jsonschema": None, "jsonschema.validators": None}):
                result = router.generate_json(
                    task_id="A10-NO-OPTIONAL-DEPS", prompt="Return a decision.", schema=SCHEMA,
                    models=["qwen3.5:4b"], invoke=lambda model, prompt, schema: VALID,
                    original_evidence={"unchanged": True}, retry_limit=0)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["value"], {"decision": "continue"})

    def test_invalid_outputs_retry_preferred_then_fall_back(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            router = self._router(Path(temporary), {"large": 2, "fallback": 1})
            calls: list[str] = []

            def invoke(model: str, prompt: str, schema: dict) -> str:
                calls.append(model)
                return "not-json" if model == "large" else VALID

            result = router.generate_json(
                task_id="A10-FALLBACK", prompt="Return a decision.", schema=SCHEMA,
                models=["large", "fallback"], invoke=invoke,
                original_evidence={"digest": "unchanged"}, retry_limit=1)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["model"], "fallback")
        self.assertEqual(calls, ["large", "large", "fallback"])
        self.assertEqual(result["original_evidence"], {"digest": "unchanged"})

    def test_daily_quota_skips_a_model_after_its_allowance_is_used(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            router = self._router(root, {"large": 1, "fallback": 2})
            calls: list[str] = []
            invoke = lambda model, prompt, schema: calls.append(model) or VALID

            first = router.generate_json("A10-Q1", "p", SCHEMA, ["large"], invoke,
                                         original_evidence={"v": 1}, retry_limit=0)
            second = router.generate_json("A10-Q2", "p", SCHEMA, ["large", "fallback"], invoke,
                                          original_evidence={"v": 2}, retry_limit=0)

        self.assertEqual(first["model"], "large")
        self.assertEqual(second["model"], "fallback")
        self.assertEqual(calls, ["large", "fallback"])

    def test_missing_models_keep_the_request_and_evidence_queued(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            router = self._router(Path(temporary))
            calls: list[str] = []
            evidence = {"source_sha256": "b" * 64}
            result = router.generate_json("A10-OFFLINE", "p", SCHEMA, [],
                lambda model, prompt, schema: calls.append(model) or VALID,
                original_evidence=evidence, retry_limit=1)

        self.assertEqual(result["status"], "WAITING_MODEL")
        self.assertEqual(result["original_evidence"], evidence)
        self.assertEqual(calls, [])

    def test_gpu_mutex_serializes_parallel_model_calls(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            mutex_name = f"Local\\NCDR-ModelRouter-{uuid.uuid4().hex}"
            routers = [ModelRouter(db_path=root / "router.sqlite", quota_per_model={"model": 4},
                                   mutex_name=mutex_name) for _ in range(2)]
            active = 0
            peak = 0
            guard = threading.Lock()
            failures: list[BaseException] = []

            def invoke(model: str, prompt: str, schema: dict) -> str:
                nonlocal active, peak
                with guard:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.08)
                with guard:
                    active -= 1
                return VALID

            def run(index: int) -> None:
                try:
                    routers[index].generate_json(f"A10-MUTEX-{index}", "p", SCHEMA, ["model"], invoke,
                        original_evidence={"index": index}, retry_limit=0)
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertEqual(failures, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
