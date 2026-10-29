import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from predictor import predict

OMSK_TZ = ZoneInfo("Asia/Omsk")


def make_topic(age_minutes=5, sources=1, posts=1):
    timestamp = (datetime.now(OMSK_TZ) - timedelta(minutes=age_minutes)).timestamp()
    return {
        "text": "В Омске произошло важное городское событие, власти сообщили подробности",
        "content_type": "news",
        "status": "take_now",
        "viral_score": 55,
        "editorial_score": 75,
        "confidence": 90,
        "posts": posts,
        "social_sources": sources,
        "official_attribution": True,
        "members": [{
            "timestamp": timestamp,
            "views": 1000,
            "likes": 35,
            "comments": 8,
            "reposts": 5,
            "text": "В Омске произошло важное городское событие",
        }],
    }


class FreshnessRankingTests(unittest.TestCase):
    def test_yesterday_topic_is_rejected(self):
        yesterday = datetime.now(OMSK_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(minutes=1)
        topic = make_topic()
        topic["members"][0]["timestamp"] = yesterday.timestamp()

        result = predict(topic)

        self.assertEqual(result["priority_score"], 0)
        self.assertEqual(result["exclusion_reason"], "not_today_or_missing_timestamp")

    def test_topic_without_timestamp_is_rejected(self):
        topic = make_topic()
        topic["members"][0].pop("timestamp")

        result = predict(topic)

        self.assertEqual(result["priority_score"], 0)
        self.assertEqual(result["exclusion_reason"], "not_today_or_missing_timestamp")

    def test_newer_topic_ranks_above_older_topic(self):
        fresh = predict(make_topic(age_minutes=3))
        older = predict(make_topic(age_minutes=90))

        self.assertGreater(fresh["priority_score"], older["priority_score"])

    def test_widely_reposted_topic_gets_saturation_penalty(self):
        limited = predict(make_topic(age_minutes=10, sources=2, posts=2))
        widespread = predict(make_topic(age_minutes=10, sources=6, posts=8))

        self.assertLess(widespread["priority_score"], limited["priority_score"])


if __name__ == "__main__":
    unittest.main()
