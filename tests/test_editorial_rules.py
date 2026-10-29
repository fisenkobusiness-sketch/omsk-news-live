import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from editorial_rules import clean_legacy_metadata, is_excluded_topic, is_promotional


class EditorialRulesTests(unittest.TestCase):
    def test_drone_and_air_alert_topics_are_excluded(self):
        self.assertTrue(is_excluded_topic({"text": "В Омской области объявили беспилотную опасность"}))
        self.assertTrue(is_excluded_topic({"text": "В городе объявили воздушную тревогу"}))
        self.assertFalse(is_excluded_topic({"text": "В Омске столкнулись три автомобиля"}))

    def test_advertorial_corporate_video_is_filtered(self):
        topic = {
            "text": (
                "От городских улиц до театральных сцен: как ОНПЗ меняет культурный облик Омска. "
                "Благодаря поддержке предприятия и программе «Родные города» учреждения искусства "
                "получают возможности для развития. В новом видеопроекте рассказывают о переменах."
            )
        }
        self.assertTrue(is_promotional(topic))

    def test_ordinary_news_is_not_filtered_as_promo(self):
        self.assertFalse(is_promotional({"text": "В Омске на Тюменской столкнулись три автомобиля"}))

    def test_legacy_verification_fields_are_removed_recursively(self):
        data = {
            "text": "Новость",
            "verification_required": True,
            "publication_mode": "verification_required",
            "members": [{
                "text": "Источник",
                "publish_disclaimer_required": True,
                "post": {"text": "Источник", "disclaimer_required": True, "views": 10},
            }],
        }
        cleaned = clean_legacy_metadata(data)
        self.assertNotIn("verification_required", cleaned)
        self.assertNotIn("publication_mode", cleaned)
        self.assertNotIn("publish_disclaimer_required", cleaned["members"][0])
        self.assertNotIn("disclaimer_required", cleaned["members"][0]["post"])
        self.assertEqual(cleaned["members"][0]["post"]["views"], 10)


if __name__ == "__main__":
    unittest.main()
