from pydantic import HttpUrl
from db.models.stories import Story, StoryInput
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from fastapi import HTTPException, FastAPI, Request, UploadFile
from typing import Any, List, Optional
from db.models.stories import UserPreview
from datetime import datetime
import os
import aiofiles
import json
from uuid import uuid4

from db.redis_client import STORY_CACHE_TTL, delete_cache, get_cache, set_cache

MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)


def convert_httpurls_to_str(data: Any):
    if isinstance(data, dict):
        return {k: convert_httpurls_to_str(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_httpurls_to_str(item) for item in data]
    elif isinstance(data, HttpUrl):
        return str(data)
    return data

async def create_text_story(db, request: Request, current_user: dict, caption: str, mentions: List[str]):
    # Build StoryInput for text
    story_input = StoryInput(
        content_url=None,
        content_type="text",
        caption=caption,
        mentions=mentions,
    )

    user_data = UserPreview(
        user_id=current_user["user_id"],
        username=current_user["username"],
        profile_pic=current_user.get("profile_image_url")
    )

    story = Story(user=user_data, details=story_input)
    return await _insert_story_to_db(db, story)


### B) Media Story Creation (image/video/audio)
async def create_media_story(db, request: Request, current_user: dict, file: UploadFile, caption: Optional[str], mentions: List[str]):
    # 1. Determine media type
    mime = file.content_type
    if mime.startswith("image/"):
        content_type = "image"
    elif mime.startswith("video/"):
        content_type = "video"
    elif mime.startswith("audio/"):
        # only allow recorded audio extensions (webm, mp3, m4a)
        if not file.filename.lower().endswith((".webm", ".mp3", ".m4a")):
            raise HTTPException(status_code=400, detail="Only recorded audio allowed.")
        content_type = "audio"
    else:
        raise HTTPException(status_code=400, detail="Unsupported media type.")

    # 2. Save file to disk
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid4()}{ext}"
    save_path = os.path.join(MEDIA_DIR, unique_name)

    async with aiofiles.open(save_path, "wb") as out_file:
        await out_file.write(await file.read())

    # 3. Build full URL (assuming localhost:8000)
    scheme = request.url.scheme
    host = request.url.hostname
    port = request.url.port or 8000
    content_url = f"{scheme}://{host}:{port}/media/{unique_name}"

    # 4. Build StoryInput
    story_input = StoryInput(
        content_url=content_url,
        content_type=content_type,
        caption=caption,
        mentions=mentions
    )

    user_data = UserPreview(
        user_id=current_user["user_id"],
        username=current_user["username"],
        profile_pic=current_user.get("profile_image_url")
    )

    story = Story(user=user_data, details=story_input)
    return await _insert_story_to_db(db, story)


### C) Common DB Insert Logic
async def _insert_story_to_db(db, story: Story):
    story_dict = convert_httpurls_to_str(story.model_dump())
    user_id = story.user.user_id

    new_story_data = {
        "story_id": story.story_id,
        "details": story_dict["details"],
        "views": [],
        "reactions": [],
        "reposts": [],
        "shares": []
    }

    await db.stories.update_one(
        {"_id": user_id},
        {
            "$setOnInsert": {"user": story_dict["user"]},
            "$push": {"stories": new_story_data}
        },
        upsert=True
    )

    await delete_cache(f"stories:{user_id}")
    return {
        "message": "Story added successfully ✅",
        "story_id": story.story_id
    }

    
async def get_all_stories(db, skip: int = 0, limit: int = 10):
    cursor = db.stories.find().skip(skip).limit(limit)
    stories = await cursor.to_list(length=limit)
    for story in stories:
        story["_id"] = str(story["_id"])
    return stories

async def get_stories_by_user_id(db, user_id: str):
    cache_key = f"stories:{user_id}"

    # 1. Redis check
    cached = await get_cache(cache_key)
    if cached:
        print("✅ Returned from Redis cache")
        return cached

    # 2. DB fallback
    doc = await db.stories.find_one({"user.user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="User has no stories")

    doc["_id"] = str(doc["_id"])

    # 3. Cache & return
    await set_cache(cache_key, doc, ttl=STORY_CACHE_TTL)
    return doc



async def update_story(db, story_id: str, user_id: str, update_data: dict):
    result = await db.stories.update_one(
        {
            "_id": user_id,
            "stories.story_id": story_id
        },
        {
            "$set": {
                **{f"stories.$.{k}": v for k, v in update_data.items()}
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Story not found or unauthorized")

    await delete_cache(f"stories:{user_id}")
    return {"message": "Story updated successfully"}



async def delete_story(db, story_id: str, user_id: str):
    doc = await db.stories.find_one({"_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="User or story not found.")

    # Find the story entry
    entry = next((s for s in doc.get("stories", []) if s["story_id"] == story_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Story not found or unauthorized.")

    # If media file exists, delete it
    details = entry.get("details", {})
    if details.get("content_url"):
        filename = details["content_url"].split("/media/")[-1]
        path = os.path.join(MEDIA_DIR, filename)
        if os.path.exists(path):
            os.remove(path)

    # Remove from array
    result = await db.stories.update_one(
        {"_id": user_id},
        {"$pull": {"stories": {"story_id": story_id}}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Story not found or unauthorized.")

    await db.users.update_one(
        {"user_id": user_id},
        {"$pull": {"stories": {"story_id": story_id}}}
    )

    await delete_cache(f"stories:{user_id}")
    return {"message": "Story (and media) deleted successfully ✅"}


async def track_story_view(db: AsyncIOMotorClient, viewer_id: str, target_id: str, story_id: str):
    """
    Record that viewer_id saw story_id under target_id.
    Also update target's ViewerLog.
    """
    # 1) WatchHistory
    await db.user_views.update_one(
        {"viewer_id": viewer_id, "target_id": target_id},
        {
            "$addToSet": {"viewed_stories": story_id},
            "$set": {"last_seen": datetime.utcnow()}
        },
        upsert=True
    )
    # 2) ViewerLog
    await db.viewer_logs.update_one(
        {"target_id": target_id},
        {
            "$addToSet": {"viewers": viewer_id},
            "$set": {"last_updated": datetime.utcnow()}
        },
        upsert=True
    )

async def load_seen_map(db: AsyncIOMotorClient, viewer_id: str) -> dict:
    """
    Returns { target_id: last_seen, ... } for all histories by viewer_id.
    """
    docs = await db.user_views.find({"viewer_id": viewer_id}).to_list(None)
    return {d["target_id"]: d["last_seen"] for d in docs}