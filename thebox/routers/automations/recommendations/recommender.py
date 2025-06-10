
from db.redis_client import get_cache, set_cache
from routers.automations.recommendations.profile_signature import matching_tags
from db.models.stories import StoryDocument, Story, UserPreview
from db.models.users import ProfileSignature
from fastapi import HTTPException
from typing import List, Dict, Set
from db.db import get_collection
import random

RECOMMENDATION_CACHE_TTL = 3600  # secs = 1h
RESPONSE_SIZE         = 10
MATCH_RATIO           = 0.45
POPULAR_RATIO         = 0.35
TEST_RATIO            = 1 - MATCH_RATIO - POPULAR_RATIO



async def build_story_document(user: dict, viewer_id: str) -> StoryDocument | None:
    story_collection = get_collection("stories")
    interaction_collection = get_collection("interactions")

    user_id = user["user_id"]

    story_doc = await story_collection.find_one({"_id": user_id})
    if not story_doc or not story_doc.get("stories"):
        return None

    interaction = await interaction_collection.find_one({
        "viewer_id": viewer_id,
        "target_id": user_id
    })

    seen_story_ids = set()
    if interaction:
        seen_story_ids.update(interaction.get("viewed_story_ids", []))
        seen_story_ids.update(interaction.get("skipped_story_ids", []))

    unseen_stories = [s for s in story_doc["stories"] if s["story_id"] not in seen_story_ids]

    if not unseen_stories:
        return None

    return StoryDocument(
        user=UserPreview(
            user_id=user_id,
            username=user.get("username"),
            profile_pic=user.get("profile_image_url")
        ),
        stories=[Story(**s) for s in unseen_stories]
    )

async def get_recommendations(user_id: str) -> List[StoryDocument]:
    db = {
        "users": get_collection("users"),
        "stories": get_collection("stories"),
        "interactions": get_collection("interactions")
    }

    me = await db["users"].find_one({"user_id": user_id})
    if not me or "profile_signature" not in me:
        raise HTTPException(status_code=404, detail="User profile not found")

    my_tags = me["profile_signature"].get("tags", [])
    location = me.get("location")
    contacts = set(me.get("contacts", []))

    # --- 1) Matched pool
    candidates = await db["users"].find({
        "user_id": {"$ne": user_id},
        "profile_signature.tags": {"$in": my_tags}
    }).to_list(length=200)

    matched = []
    for o in candidates:
        other_sig = ProfileSignature(**o["profile_signature"])
        shared = set(my_tags) & set(other_sig.tags)
        if shared:
            score = len(shared) * 5 + other_sig.profile_score
            story_doc = await build_story_document(o, user_id)
            if story_doc:
                matched.append((score, story_doc))

    matched.sort(key=lambda x: x[0], reverse=True)
    matched = [sd for _, sd in matched]

    # --- 2) Popular pool
    popular_raw = []
    if location:
        local = await db["users"].find({
            "user_id": {"$ne": user_id},
            "location": location,
            "profile_signature.profile_score": {"$gte": 50}
        }).sort("profile_signature.profile_score", -1).limit(5).to_list(5)
        popular_raw.extend(local)

    global_pop = await db["users"].find({
        "user_id": {"$ne": user_id},
        "profile_signature.profile_score": {"$gte": 50}
    }).sort("profile_signature.profile_score", -1).limit(10).to_list(10)

    popular_raw.extend([u for u in global_pop if u not in popular_raw])

    popular = []
    for u in popular_raw:
        story_doc = await build_story_document(u, user_id)
        if story_doc:
            popular.append(story_doc)

    # --- 3) Test pool (low score + contacts)
    test_raw = []
    if location:
        newbies = await db["users"].find({
            "user_id": {"$ne": user_id},
            "location": location,
            "profile_signature.profile_score": {"$lte": 40}
        }).limit(20).to_list(20)
        test_raw.extend(newbies)

    if contacts:
        contact_users = await db["users"].find({
            "user_id": {"$in": list(contacts)},
            "user_id": {"$ne": user_id}
        }).limit(20).to_list(20)
        test_raw.extend(contact_users)

    seen_ids: Set[str] = set()
    test = []
    for u in test_raw:
        uid = u["user_id"]
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        story_doc = await build_story_document(u, user_id)
        if story_doc:
            test.append(story_doc)

    # --- 4) Sample & combine
    m_cnt = min(int(RESPONSE_SIZE * MATCH_RATIO), len(matched))
    p_cnt = min(int(RESPONSE_SIZE * POPULAR_RATIO), len(popular))
    t_cnt = RESPONSE_SIZE - m_cnt - p_cnt

    m_sample = matched[:m_cnt]
    p_sample = random.sample(popular, p_cnt) if p_cnt and len(popular) >= p_cnt else []
    t_sample = random.sample(test, t_cnt) if t_cnt and len(test) >= t_cnt else []

    combined = m_sample + p_sample + t_sample

    # --- 5) Fallback fill
    if len(combined) < RESPONSE_SIZE:
        leftovers = (
            matched[m_cnt:] +
            [p for p in popular if p not in p_sample] +
            [t for t in test if t not in t_sample]
        )
        combined.extend(leftovers[:RESPONSE_SIZE - len(combined)])

    random.shuffle(combined)
    return combined[:RESPONSE_SIZE]


async def recommend_users_from_signature(db, signature: ProfileSignature) -> List[dict]:
    tags = matching_tags(signature)
    if not tags:
        return []
    query = {
        "profile_signature": {"$exists": True},
        "$or": [
            {"profile_signature.behavioral_tags": {"$in": tags}},
            {"profile_signature.interests": {"$in": tags}},
            {"profile_signature.bio_tags": {"$in": tags}},
            {"profile_signature.category": {"$in": tags}}
        ]
    }
    users = await db.users.find(query).limit(100).to_list(100)
    scored = []
    for user in users:
        other_sig = ProfileSignature(**user["profile_signature"])
        other_tags = matching_tags(other_sig)
        shared = set(tags) & set(other_tags)
        if not shared:
            continue
        score = len(shared) * 5 + other_sig.profile_score
        scored.append({
            "user_id": user["user_id"],
            "username": user.get("username"),
            "profile_image_url": user.get("profile_image_url"),
            "score": score,
            "reason": list(shared)
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:30]
