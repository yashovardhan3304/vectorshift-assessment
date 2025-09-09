import os
import time
from typing import Optional, Tuple
import redis.asyncio as redis
from kombu.utils.url import safequote

redis_host = safequote(os.environ.get('REDIS_HOST', 'localhost'))
redis_client = redis.Redis(host=redis_host, port=6379, db=0)

# In-memory fallback store for local testing when Redis is unavailable
_memory_store: dict[str, Tuple[bytes, Optional[float]]] = {}

async def add_key_value_redis(key, value, expire=None):
    try:
        await redis_client.set(key, value)
        if expire:
            await redis_client.expire(key, expire)
    except Exception:
        # Fallback to in-memory store
        expire_at = time.time() + expire if expire else None
        _memory_store[str(key)] = (value if isinstance(value, (bytes, bytearray)) else str(value).encode(), expire_at)

async def get_value_redis(key):
    try:
        return await redis_client.get(key)
    except Exception:
        # Fallback read
        entry = _memory_store.get(str(key))
        if not entry:
            return None
        value, expire_at = entry
        if expire_at is not None and time.time() > expire_at:
            # expired; remove and return None
            _memory_store.pop(str(key), None)
            return None
        return value

async def delete_key_redis(key):
    try:
        await redis_client.delete(key)
    except Exception:
        _memory_store.pop(str(key), None)
