import tempfile
from contextlib import closing
import unittest
import sys
import sqlite3
from unittest.mock import Mock
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import smm_poiskovik_engagement_tracker as tracker
from smm_poiskovik_engagement_tracker import (
    AUDIENCES, completed_counts, init_db, maybe_notify_threshold, unseen_posts,
    process_due_observations,
)



class VkCallTests(unittest.TestCase):
    @patch.object(tracker.requests, "get")
    def test_vk_call_returns_response_payload(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"response": {"items": [1]}}
        mock_get.return_value = mock_response
        self.assertEqual(tracker.vk_call("token", "wall.get", count=1), {"items": [1]})

    @patch.object(tracker.requests, "get")
    def test_vk_call_handles_string_error_without_attribute_error(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"error": "access denied"}
        mock_get.return_value = mock_response
        with self.assertRaisesRegex(RuntimeError, "access denied"):
            tracker.vk_call("token", "wall.get")

    @patch.object(tracker.requests, "get")
    def test_vk_call_rejects_response_without_response_field(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"unexpected": "payload"}
        mock_get.return_value = mock_response
        with self.assertRaisesRegex(RuntimeError, "отсутствует поле response"):
            tracker.vk_call("token", "wall.get")


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "tracker.sqlite3"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def add_observation(self, audience, predicted_at):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute(
                """INSERT INTO observations (
                    observation_id, audience, audience_name, member_posts_json,
                    member_ids_json, predicted_at, score, prediction, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"{audience}-{predicted_at}", audience, AUDIENCES[audience]["name"],
                 "[]", "[123]", predicted_at, 42.0, "НАБЛЮДАТЬ", predicted_at),
            )
            db.commit()

    def test_first_poll_bootstraps_without_evaluation(self):
        self.assertEqual(unseen_posts(self.db, "golos", [{"id": 1}, {"id": 2}]), [])
        self.assertEqual(unseen_posts(self.db, "golos", [{"id": 1}, {"id": 2}]), [])

    def test_new_posts_are_returned_once(self):
        unseen_posts(self.db, "golos", [{"id": 1}])
        self.assertEqual([p["id"] for p in unseen_posts(self.db, "golos", [{"id": 1}, {"id": 2}])], [2])
        self.assertEqual(unseen_posts(self.db, "golos", [{"id": 2}]), [])

    def test_counts_start_at_zero(self):
        self.assertEqual(completed_counts(self.db), {"golos": 0, "zhest": 0})

    def test_threshold_does_not_notify_until_both_cohorts_ready(self):
        calls = []
        self.assertFalse(maybe_notify_threshold(self.db, send_func=lambda *args: calls.append(args),
                                                token="token", chat_id="chat", threshold=1))
        self.assertEqual(calls, [])

    def test_threshold_notifies_once_when_both_cohorts_are_ready(self):
        self.add_observation("golos", 1000)
        self.add_observation("zhest", 1000)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE observations SET completed_1h=1, completed_3h=1")
            db.commit()
        calls = []
        send = lambda *args: calls.append(args)
        self.assertTrue(maybe_notify_threshold(self.db, send_func=send, token="token", chat_id="chat", threshold=1))
        self.assertFalse(maybe_notify_threshold(self.db, send_func=send, token="token", chat_id="chat", threshold=1))
        self.assertEqual(len(calls), 1)

    def test_due_one_hour_checkpoint_is_recorded(self):
        predicted_at = 10_000
        self.add_observation("golos", predicted_at)
        counters = {123: {"views": 100, "likes": 10, "comments": 2, "reposts": 1}}
        with patch.object(tracker, "fetch_post_counters", return_value=counters), patch.object(tracker, "log"):
            process_due_observations("token", self.db, now=predicted_at + 3600)
        with closing(sqlite3.connect(self.db)) as db:
            row = db.execute("SELECT completed_1h, score_at_1h, completed_3h FROM observations").fetchone()
        self.assertEqual(row[0], 1)
        self.assertAlmostEqual(row[1], (10 + 2 * 2 + 4 * 1) / 100)
        self.assertEqual(row[2], 0)

    def test_late_one_hour_checkpoint_is_marked_missed_not_completed(self):
        predicted_at = 10_000
        self.add_observation("golos", predicted_at)
        with patch.object(tracker, "fetch_post_counters") as fetch, patch.object(tracker, "log"):
            process_due_observations("token", self.db, now=predicted_at + 3600 + 601)
        with closing(sqlite3.connect(self.db)) as db:
            row = db.execute("SELECT completed_1h, missed_1h FROM observations").fetchone()
        self.assertEqual(row, (0, 1))
        fetch.assert_not_called()

    def test_partial_counter_response_does_not_complete_checkpoint(self):
        predicted_at = 10_000
        self.add_observation("golos", predicted_at)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE observations SET member_ids_json='[123,456]'")
            db.commit()
        counters = {123: {"views": 100, "likes": 10, "comments": 2, "reposts": 1}}
        with patch.object(tracker, "fetch_post_counters", return_value=counters), patch.object(tracker, "log"):
            process_due_observations("token", self.db, now=predicted_at + 3600)
        with closing(sqlite3.connect(self.db)) as db:
            row = db.execute("SELECT completed_1h, views_at_1h FROM observations").fetchone()
        self.assertEqual(row, (0, None))

    def test_target_audience_ids(self):
        self.assertEqual(AUDIENCES["golos"]["group_id"], 133335843)
        self.assertEqual(AUDIENCES["zhest"]["group_id"], 76091195)


if __name__ == "__main__":
    unittest.main()
