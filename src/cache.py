import json
import logging

import fakeredis

logger = logging.getLogger(__name__)


class MovieCache:
    def __init__(self):
        self.client = fakeredis.FakeRedis(decode_responses=True)

    @staticmethod
    def make_key(limit):
        return f"movies:limit:{limit}"

    def get(self, limit):
        key = self.make_key(limit)
        cached = self.client.get(key)
        logger.debug("Cache %s: %s", "HIT" if cached is not None else "MISS", key)
        return json.loads(cached) if cached is not None else None

    def set(self, limit, response):
        self.client.set(self.make_key(limit), json.dumps(response), ex=90)

    def invalidate(self):
        self.client.flushdb()
        logger.debug("Invalidated movie cache")
