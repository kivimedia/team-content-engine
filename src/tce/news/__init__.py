"""The third lane: news that connects to Ziv's work.

Stage A is deterministic and lives here: build the anchor index (`anchors`),
fetch feeds (`feeds`), match items against the index (`matcher`). No model call
happens in any of it, which is what makes daily discovery free on a quiet day.

Stage B (`appraise`) is one subscription job per matched item.
"""
