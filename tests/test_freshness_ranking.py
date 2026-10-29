import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from predictor import predict

OMSK_TZ = ZoneInfo("Asia/Omsk")


def make_topic(age_minutes=5, sources=1, posts=1, text=None, metrics=True, confidence=90):
    timestamp = (datetime.now(OMSK_TZ) - timedelta(minutes=age_minutes)).timestamp()
    member = {
        "timestamp": timestamp,
        "text": text or "В Омске произошло важное городское событие, власти сообщили подробности",
    }
    if metrics:
        member.update({"views": 1000, "likes": 35, "comments": 8, "reposts": 5})
    return {
        "text": text or "В Омске произошло важное городское событие, власти сообщили подробности",
        "content_type": "news",
        "status": "take_now",
        # Legacy scores are deliberately present: v2 must not double-count them.
        "score": 75,
        "viral_score": 55,
        "editorial_score": 75,
        "confidence": confidence,
        "posts": posts,
        "social_sources": sources,
        "members": [member],
    }


class EditorialRankingTests(unittest.TestCase):
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

    def test_public_safety_event_ranks_above_generic_story_with_same_evidence(self):
        generic = predict(make_topic(
            age_minutes=10, metrics=False,
            text="В Омске сообщили о новом городском мероприятии",
        ))
        evacuation = predict(make_topic(
            age_minutes=10, metrics=False,
            text="В Омске эвакуировали сотрудников и посетителей здания",
        ))

        self.assertEqual(evacuation["event_class"], "public_safety")
        self.assertGreater(evacuation["priority_score"], generic["priority_score"])

    def test_missing_metrics_are_exposed_instead_of_treated_as_measured_zero(self):
        result = predict(make_topic(metrics=False))

        self.assertEqual(result["metric_coverage"], [])
        self.assertEqual(result["coverage_ratio"], 0)
        self.assertIsNone(result["signals"]["reach"])
        self.assertIsNone(result["signals"]["engagement"])

    def test_confidence_is_verification_metadata_not_popularity(self):
        high_confidence = predict(make_topic(confidence=90))
        low_confidence = predict(make_topic(confidence=10))

        self.assertEqual(high_confidence["priority_score"], low_confidence["priority_score"])
        self.assertFalse(high_confidence["verification_required"])
        # A low confidence score alone must not block an ordinary local story.
        self.assertFalse(low_confidence["verification_required"])

        high_risk = predict(make_topic(
            confidence=10,
            text="В Омске в ДТП погиб водитель автомобиля",
            metrics=False,
        ))
        self.assertTrue(high_risk["verification_required"])
        self.assertTrue(high_risk["disclaimer_required"])

    def test_legacy_scores_are_diagnostic_only(self):
        first = make_topic()
        second = make_topic()
        second["viral_score"] = 0
        second["editorial_score"] = 0
        second["score"] = 0

        self.assertEqual(predict(first)["priority_score"], predict(second)["priority_score"])

    def test_excluded_topics_remain_hard_filtered(self):
        topic = make_topic(text="В Омской области объявили беспилотную опасность")

        result = predict(topic)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["exclusion_reason"], "excluded_topic")

    def test_editorial_action_uses_score_and_verification_gate(self):
        from predictor import apply_editorial_action

        item = {"status": "take_now", "action": "БРАТЬ"}
        apply_editorial_action(item, {
            "priority_score": 90,
            "verification_required": True,
            "disclaimer_required": True,
        })
        self.assertEqual(item["status"], "watch")
        self.assertEqual(item["action"], "НАБЛЮДАТЬ")
        self.assertEqual(item["publication_mode"], "verification_required")

        item = {"status": "watch", "action": "НАБЛЮДАТЬ"}
        apply_editorial_action(item, {
            "priority_score": 55,
            "verification_required": False,
            "disclaimer_required": False,
        })
        self.assertEqual(item["status"], "check")
        self.assertEqual(item["action"], "ПРОВЕРИТЬ")

        item = {}
        apply_editorial_action(item, {
            "priority_score": 75,
            "verification_required": False,
            "disclaimer_required": False,
        })
        self.assertEqual(item["status"], "take_now")
        self.assertEqual(item["action"], "БРАТЬ")

    def test_reference_to_deceased_people_does_not_make_story_fatal_incident(self):
        topic = make_topic(
            text="Фонд помогает детям погибших и пропавших без вести защитников",
            metrics=False,
        )

        result = predict(topic)

        self.assertEqual(result["event_class"], "general")
        self.assertEqual(result["signals"]["event_impact"], 20.0)

    def test_actual_fatality_is_classified_as_fatal_incident(self):
        topic = make_topic(
            text="В Омске в ДТП погиб водитель автомобиля",
            metrics=False,
        )

        result = predict(topic)

        self.assertEqual(result["event_class"], "fatal_incident")
        self.assertEqual(result["signals"]["event_impact"], 100.0)


if __name__ == "__main__":
    unittest.main()
