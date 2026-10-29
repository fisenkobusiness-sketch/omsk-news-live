"""Обратная совместимость: общие метрики хранятся только в src/metrics.py."""
from src.metrics import aggregate_topic_stats, newest_timestamp, topic_age_hours

__all__ = ["aggregate_topic_stats", "newest_timestamp", "topic_age_hours"]
