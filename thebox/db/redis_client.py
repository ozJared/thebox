import redis.asyncio as redis
import json

# Async Redis client
redis_client = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)


# Set cache with TTL
PROFILE_CACHE_TTL = 60 * 60 * 24 * 30   # 2 months
STORY_CACHE_TTL = 60 * 60 * 24          # 24 hours

async def set_cache(key: str, data: dict, ttl: int = PROFILE_CACHE_TTL):
    await redis_client.set(key, json.dumps(data), ex=ttl)



# Get cache
async def get_cache(key: str):
    data = await redis_client.get(key)
    return json.loads(data) if data else None

# Delete cache
async def delete_cache(key: str):
    await redis_client.delete(key)
