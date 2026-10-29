import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from predictor import predict
from analysis import classify, classify_editorial_status

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
    def test_analysis_uses_only_work_or_reject_statuses(self):
        cases = [
            ({"score": 70}, "take_now"),
            ({"score": 20}, "reject"),
            ({"score": 99, "help_only": True}, "reject"),
            ({"score": 10, "complaint_viral_signal": True}, "take_now"),
            ({"score": 99, "nonlocal_only": True}, "reject"),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                status, _ = classify_editorial_status(**kwargs)
                self.assertEqual(status, expected)
                self.assertIn(status, {"take_now", "reject"})

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

    def test_confidence_is_diagnostic_only_and_has_no_verification_gate(self):
        high_confidence = predict(make_topic(confidence=90))
        low_confidence = predict(make_topic(confidence=10))

        self.assertEqual(high_confidence["priority_score"], low_confidence["priority_score"])
        self.assertNotIn("verification_required", high_confidence)
        self.assertNotIn("disclaimer_required", high_confidence)
        # Low confidence must not create a verification gate or output field.
        self.assertNotIn("verification_required", low_confidence)
        self.assertNotIn("disclaimer_required", low_confidence)

        high_risk = predict(make_topic(
            confidence=10,
            text="В Омске в ДТП погиб водитель автомобиля",
            metrics=False,
        ))
        self.assertNotIn("verification_required", high_risk)
        self.assertNotIn("disclaimer_required", high_risk)

    def test_legacy_scores_are_diagnostic_only(self):
        first = make_topic()
        second = make_topic()
        second["viral_score"] = 0
        second["editorial_score"] = 0
        second["score"] = 0

        self.assertEqual(predict(first)["priority_score"], predict(second)["priority_score"])

    def test_corporate_advertorial_is_hard_filtered(self):
        topic = make_topic(
            metrics=False,
            text=(
                "От городских улиц до театральных сцен: как ОНПЗ меняет культурный облик Омска. "
                "Благодаря поддержке предприятия и программе «Родные города» учреждения искусства "
                "получают возможности для развития. В новом видеопроекте рассказывают о переменах."
            ),
        )
        result = predict(topic)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["exclusion_reason"], "promotional")

    def test_excluded_topics_remain_hard_filtered(self):
        topic = make_topic(text="В Омской области объявили беспилотную опасность")

        result = predict(topic)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["exclusion_reason"], "excluded_topic")

    def test_low_priority_status_does_not_hard_filter_ordinary_local_news(self):
        topic = make_topic(text="В Омске сообщили о городском решении", metrics=False)
        topic["status"] = "reject"

        result = predict(topic)

        self.assertTrue(result["eligible"])
        self.assertIsNone(result["exclusion_reason"])

    def test_explicit_advertising_and_nonlocal_flags_remain_hard_filtered(self):
        ad = make_topic(text="В Омске сообщили о событии", metrics=False)
        ad["status"] = "reject"
        ad["content_type"] = "advertising"
        self.assertEqual(predict(ad)["exclusion_reason"], "advertising")

        nonlocal_topic = make_topic(text="В Омске сообщили о событии", metrics=False)
        nonlocal_topic["nonlocal_detected"] = True
        self.assertEqual(predict(nonlocal_topic)["exclusion_reason"], "nonlocal_topic")

    def test_editorial_action_has_only_work_or_reject_statuses(self):
        from predictor import apply_editorial_action

        item = {"status": "take_now", "action": "БРАТЬ"}
        apply_editorial_action(item, {
            "priority_score": 90,
        })
        self.assertEqual(item["status"], "take_now")
        self.assertEqual(item["action"], "БРАТЬ В РАБОТУ")
        self.assertEqual(item["publication_mode"], "editorial_work")
        self.assertIsNone(item["editorial_exclusion_reason"])
        self.assertNotIn("verification_required", item)
        self.assertNotIn("publish_disclaimer_required", item)

        item = {"status": "watch", "action": "НАБЛЮДАТЬ"}
        apply_editorial_action(item, {
            "priority_score": 55,
        })
        self.assertEqual(item["status"], "take_now")
        self.assertEqual(item["action"], "БРАТЬ В РАБОТУ")

        item = {}
        apply_editorial_action(item, {
            "priority_score": 30,
        })
        self.assertEqual(item["status"], "reject")
        self.assertEqual(item["action"], "ИСКЛЮЧИТЬ")
        self.assertEqual(item["editorial_exclusion_reason"], "below_priority_threshold")


    def test_mention_of_police_without_explicit_attribution_is_not_official(self):
        result = classify({
            "text": "Жители жалуются на потоп. Полиция приехала на место, официального комментария в сообщении нет.",
            "source": "Очевидец",
        })
        self.assertFalse(result["official_attribution"])
        self.assertEqual(result["source_type"], "complaint")

    def test_explicit_official_statement_is_attributed_but_eyewitness_is_not(self):
        official = classify({
            "text": "По данным прокуратуры, проверка началась сегодня в Омске.",
            "source": "Региональный канал",
        })
        eyewitness = classify({
            "text": "По словам очевидцев, проверка началась сегодня в Омске.",
            "source": "Региональный канал",
        })
        self.assertTrue(official["official_attribution"])
        self.assertFalse(eyewitness["official_attribution"])

    def test_pet_adoption_listing_with_phone_is_not_news(self):
        result = classify({
            "text": "Пристройство кота Барсика, звоните 8 913 123-45-67",
            "source": "Житель Омска",
        })
        self.assertEqual(result["content_type"], "help_request")
        self.assertTrue(result["help_request"])

    def test_sports_interview_is_capped_below_priority_threshold(self):
        topic = make_topic(
            text="В Омске хоккеист Глеб Бурала дал интервью после матча",
            metrics=True,
        )
        result = predict(topic)
        self.assertLessEqual(result["priority_score"], 40.0)
        self.assertNotIn("verification_required", result)

    def test_event_announcement_is_not_automatically_high_priority(self):
        topic = make_topic(
            text="В Омске состоится автограф-сессия бывших капитанов Авангарда",
            metrics=True,
        )
        result = predict(topic)
        self.assertLessEqual(result["priority_score"], 42.0)
        self.assertEqual(result["event_class"], "general")

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
