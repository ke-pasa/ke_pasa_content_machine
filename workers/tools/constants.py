"""
Shared constants for workers.
"""

# Minimum total_score threshold for article processing
MIN_ARTICLE_SCORE = 65

# Minimum total_score threshold for publishing to Telegram
MIN_PUBLISH_SCORE = 80

# Derived thresholds used by categorization buckets.
# short note threshold is slightly above the minimum article score.
SHORT_NOTE_THRESHOLD = MIN_ARTICLE_SCORE 

# publish threshold is slightly above the minimum publish score.
PUBLISH_THRESHOLD = MIN_PUBLISH_SCORE
