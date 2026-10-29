"""Regression tests for early viral-signal ranking in the editorial predictor."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from predictor import predict  # noqa: E402


def post(source: str, *, views: int = 1000, timestamp: float | None = None) -> dict:
    return {
        "source": source,
        "timestamp": timestamp if timestamp is not None else time.time(),
        "text": "В Омске обсуждают важное городское событие",
        "views": views,
        "likes": 10,
        "comments": 5,
        "reposts": 2,
    }


class EarlyViralSignalTests(unittest.TestCase):
    def test_independent_sources_raise_priority_without_extra_views(self):
        now = time.time()
        one_source = {
            "text": "В Омске обсуждают важное городское событие",
            "content_type": "news",
            "members": [post("source-a", views=3000, timestamp=now)],
        }
        three_sources = {
            "text": "В Омске обсуждают важное городское событие",
            "content_type": "news",
            "members": [
                post("source-a", views=1000, timestamp=now),
                post("source-b", views=1000, timestamp=now),
                post("source-c", views=1000, timestamp=now),
            ],
        }

        single_result = predict(one_source)
        spread_result = predict(three_sources)

        self.assertTrue(single_result["eligible"])
        self.assertTrue(spread_result["eligible"])
        self.assertEqual(spread_result["cross_source_count"], 3)
        self.assertGreater(
            spread_result["priority_score"],
            single_result["priority_score"],
        )

    def test_viral_complaint_is_a_rankable_signal_without_official_confirmation(self):
        now = time.time()
        topic = {
            "text": "Жители Омска жалуются на постоянные потопы и канализацию",
            "content_type": "complaint",
            "confidence": 10,
            "members": [
                post("source-a", views=2000, timestamp=now),
                post("source-b", views=2000, timestamp=now),
                post("source-c", views=2000, timestamp=now),
            ],
        }

        result = predict(topic)

        self.assertTrue(result["eligible"])
        self.assertTrue(result["complaint_signal"])
        self.assertTrue(result["complaint_viral_signal"])
        self.assertEqual(result["complaint_bonus"], 8.0)
        self.assertIsNone(result["exclusion_reason"])

    def test_confidence_does_not_change_priority_score(self):
        now = time.time()
        base = {
            "text": "В Омске изменили правила городского транспорта",
            "content_type": "news",
            "members": [post("source-a", views=2500, timestamp=now)],
        }

        low_confidence = predict({**base, "confidence": 10})
        high_confidence = predict({**base, "confidence": 95})

        self.assertEqual(
            low_confidence["priority_score"],
            high_confidence["priority_score"],
        )

    def test_hard_excluded_topic_remains_excluded_despite_viral_metrics(self):
        now = time.time()
        topic = {
            "text": "В Омской области объявили беспилотную опасность",
            "content_type": "news",
            "members": [
                post("source-a", views=20000, timestamp=now),
                post("source-b", views=20000, timestamp=now),
                post("source-c", views=20000, timestamp=now),
            ],
        }

        result = predict(topic)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["exclusion_reason"], "excluded_topic")
        self.assertEqual(result["priority_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
