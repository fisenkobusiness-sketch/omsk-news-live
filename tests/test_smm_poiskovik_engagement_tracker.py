import tempfile
import unittest
from pathlib import Path
from smm_poiskovik_engagement_tracker import AUDIENCES, completed_counts, init_db, maybe_notify_threshold, unseen_posts

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "tracker.sqlite3"
        init_db(self.db)
    def tearDown(self):
        self.tmp.cleanup()
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
    def test_target_audience_ids(self):
        self.assertEqual(AUDIENCES["golos"]["group_id"], 133335843)
        self.assertEqual(AUDIENCES["zhest"]["group_id"], 76091195)

if __name__ == "__main__":
    unittest.main()
