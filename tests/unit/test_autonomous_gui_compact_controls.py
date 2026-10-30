from __future__ import annotations

from datetime import datetime, timezone
import unittest

from src.agent.autonomous_gui_compact import ManagerWindow, derive_ai_status


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeTree:
    def __init__(self):
        self.rows = {"7": ()}
        self.selected = ("7",)
        self.position = (0.4, 0.7)

    def get_children(self):
        return tuple(self.rows)

    def delete(self, item):
        self.rows.pop(item, None)

    def selection(self):
        return self.selected

    def yview(self):
        return self.position

    def insert(self, _parent, _where, *, iid, values, tags):
        self.rows[iid] = (values, tags)

    def selection_set(self, items):
        self.selected = tuple(items)

    def focus(self, _item):
        pass

    def yview_moveto(self, position):
        self.position = (position, position + 0.3)


class _FakeWidget:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


class _FakeRoot:
    def __init__(self):
        self.calls = []

    def after(self, delay, callback):
        self.calls.append((delay, callback))
        return "after-id"

    def after_cancel(self, _after_id):
        pass


class CompactQueueSortingTests(unittest.TestCase):
    def test_attempts_are_sorted_numerically(self) -> None:
        self.assertLess(ManagerWindow._queue_sort_key({"attempts": 2}, "attempts"),
                        ManagerWindow._queue_sort_key({"attempts": 10}, "attempts"))

    def test_status_groups_follow_the_requested_order(self) -> None:
        ordered = ["DONE", "RUNNING", "PENDING", "BLOCKED", "WAITING_EXTERNAL", "ERROR"]
        ranks = [ManagerWindow._queue_status_rank(value)[0] for value in ordered]
        self.assertEqual(ranks, sorted(ranks))

    def test_updated_time_uses_datetime_order(self) -> None:
        early = ManagerWindow._queue_sort_key({"updated_utc": "2026-10-28T09:05:00+00:00"}, "updated")
        late = ManagerWindow._queue_sort_key({"updated_utc": "2026-10-28T17:02:00+00:00"}, "updated")
        self.assertLess(early, late)

    def test_task_name_sort_includes_handler_type(self) -> None:
        first = ManagerWindow._queue_sort_key({"id": "AUTO_A", "agent": "reader"}, "#0")
        second = ManagerWindow._queue_sort_key({"id": "AUTO_A", "agent": "writer"}, "#0")
        self.assertLess(first, second)


class LocalAIStatusTests(unittest.TestCase):
    NOW = datetime(2026, 10, 28, 18, 22, 30, tzinfo=timezone.utc)

    @staticmethod
    def event(name: str, created: str, detail: dict) -> dict:
        import json
        return {"id": 10, "event": name, "created_utc": created,
                "detail_json": json.dumps(detail)}

    def test_live_request_is_green_even_if_gui_health_probe_is_blocked(self) -> None:
        state = {"events": [self.event("ollama_request_started", "2026-10-28T18:22:20+00:00",
            {"model": "qwen3.5:9b", "role": "project-director", "started_utc": "2026-10-28T18:22:20+00:00"})],
            "ollama_status_known": True, "ollama_error": "PermissionError: [WinError 10013]"}
        result = derive_ai_status(state, now_utc=self.NOW)
        self.assertEqual(result["level"], "green")
        self.assertEqual(result["model"], "qwen3.5:9b")

    def test_restricted_health_probe_is_unknown_not_false_outage(self) -> None:
        state = {"events": [self.event("ollama_request_completed", "2026-10-28T18:22:20+00:00",
            {"model": "qwen3.5:9b", "role": "project-director", "elapsed_ms": 15683})],
            "ollama_status_known": True, "ollama_models": [],
            "ollama_error": "PermissionError: [WinError 10013] access denied"}
        result = derive_ai_status(state, now_utc=self.NOW)
        self.assertEqual(result["level"], "gray")
        self.assertEqual(result["model"], "qwen3.5:9b")
        self.assertIn("не встановлена", result["label"])

    def test_recent_model_call_failure_is_red_even_if_tags_probe_succeeds(self) -> None:
        state = {"events": [self.event("ollama_request_failed", "2026-10-28T18:22:20+00:00",
            {"model": "qwen3.5:9b", "role": "project-director", "elapsed_ms": 1500,
             "error": "structured response failed"})],
            "ollama_status_known": True, "ollama_models": ["qwen3.5:9b"]}
        result = derive_ai_status(state, now_utc=self.NOW)
        self.assertEqual(result["level"], "red")
        self.assertEqual(result["label"], "Помилка запиту моделі")

    def test_empty_event_history_is_a_valid_idle_state(self) -> None:
        result = derive_ai_status({"events": [], "ollama_status_known": True,
            "ollama_models": ["qwen3.5:9b"]}, now_utc=self.NOW)
        self.assertEqual(result["level"], "yellow")
        self.assertIsNone(result["last_activity"])

    def test_no_event_history_and_unknown_ollama_state_is_gray(self) -> None:
        result = derive_ai_status({"events": [], "ollama_status_known": False}, now_utc=self.NOW)
        self.assertEqual(result["level"], "gray")
        self.assertIsNone(result["model"])


class ModelHistoryRefreshTests(unittest.TestCase):
    def test_refresh_preserves_selected_run_and_scroll_position(self) -> None:
        window = ManagerWindow.__new__(ManagerWindow)
        window.ai_runs = _FakeTree()
        window.ai_model_filter = _Var("Усі")
        window.ai_status_filter = _Var("Усі")
        window.ai_period_filter = _Var("Усі доступні")
        window.ai_rows = {"7": {"id": 7, "task_id": "DIRECTOR_ANALYSIS_7",
            "model": "qwen3.5:9b", "role": "project-director", "status": "OK",
            "created_utc": "2026-10-28T18:22:20+00:00", "elapsed_ms": 1000}}
        window.show_model_text = _Var(False)
        window._render_ai_runs()
        self.assertEqual(window.ai_runs.selection(), ("7",))
        self.assertEqual(window.ai_runs.position[0], 0.4)


class ResearchControlButtonTests(unittest.TestCase):
    @staticmethod
    def make_window():
        window = ManagerWindow.__new__(ManagerWindow)
        window.play_pause_button = _FakeWidget()
        window.stop_button = _FakeWidget()
        window.control_reason = _Var("")
        window.root = _FakeRoot()
        window._blink_after_id = None
        window._blink_phase = False
        return window

    def test_stopped_without_pending_work_still_offers_green_resume(self) -> None:
        window = self.make_window()
        window._refresh_control_button({"control": {"desired_state": "STOPPED"},
            "queue_diagnosis": {"eligible_task_ids": []}, "tasks": []}, worker_alive=False)
        self.assertEqual(window._control_mode, "STOPPED")
        self.assertEqual(window.play_pause_button.options["bg"], "#07845f")
        self.assertEqual(window.play_pause_button.options["text"], "▶")
        self.assertEqual(window.stop_button.options["state"], "disabled")

    def test_active_task_uses_red_pause_and_starts_blink_timer(self) -> None:
        window = self.make_window()
        window._refresh_control_button({"control": {"desired_state": "RUNNING",
            "current_task": "t1"}, "queue_diagnosis": {},
            "tasks": [{"id": "t1", "status": "LEASED"}]}, worker_alive=True)
        self.assertEqual(window._control_mode, "RUNNING")
        self.assertEqual(window.play_pause_button.options["text"], "⏸")
        self.assertEqual(window.play_pause_button.options["bg"], "#bd3932")
        self.assertEqual(window.root.calls[0][0], 500)

    def test_blocked_running_worker_uses_static_red_play(self) -> None:
        window = self.make_window()
        window._refresh_control_button({"control": {"desired_state": "RUNNING",
            "last_error": "no runnable task"}, "queue_diagnosis": {"message": "empty"},
            "tasks": []}, worker_alive=True)
        self.assertEqual(window._control_mode, "BLOCKED")
        self.assertEqual(window.play_pause_button.options["text"], "▶")
        self.assertEqual(window.play_pause_button.options["bg"], "#bd3932")
        self.assertEqual(window.root.calls, [])

    def test_single_button_dispatches_each_state_to_the_matching_action(self) -> None:
        for state, expected in (("RUNNING", "pause"), ("PAUSED", "resume"),
                                ("READY", "start"), ("STOPPED", "start"),
                                ("BLOCKED", "director"), ("ERROR", "director")):
            with self.subTest(state=state):
                window = ManagerWindow.__new__(ManagerWindow)
                window._control_mode = state
                calls = []
                window.pause = lambda: calls.append("pause")
                window.resume = lambda: calls.append("resume")
                window.start = lambda: calls.append("start")
                window.request_director_analysis = lambda: calls.append("director")
                window.toggle_research()
                self.assertEqual(calls, [expected])


if __name__ == "__main__":
    unittest.main()
