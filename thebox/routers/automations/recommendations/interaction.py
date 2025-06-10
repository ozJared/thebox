from fastapi import APIRouter, Request, HTTPException, Depends, File, UploadFile, Form
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from routers.crud.stories import track_story_view
from routers.automations.recommendations.profile_signature import update_behavioral_tags
from db.redis_client import delete_cache
from db.models.users import ProfileSignature
from security.dependencies import get_current_user
from uuid import uuid4
import os, aiofiles

router = APIRouter(prefix="/interactions", tags=["Interactions"])

# Interaction weights
ACTION_WEIGHTS = {"view":1,"skip":-2,"react":2,"share":3,"repost":2}
PROFILE_LIMITS = {"min":25,"max":200}

async def adjust_profile_score(db, target_id: str, delta: int):
    u = await db.users.find_one({"user_id":target_id})
    if not u: return
    cur = u.get("profile_signature",{}).get("profile_score",50)
    new = max(PROFILE_LIMITS["min"], min(cur+delta, PROFILE_LIMITS["max"]))
    await db.users.update_one({"user_id":target_id},{"$set":{"profile_signature.profile_score":new}})

@router.post("/view/{story_id}")
async def view_story(story_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    db: AsyncIOMotorClient = request.app.mongodb
    viewer = current_user["user_id"]
    # find story owner
    doc = await db.stories.find_one({"stories.story_id":story_id})
    if not doc: raise HTTPException(404,"Story not found")
    owner = doc["_id"]
    # record view
    await track_story_view(db, viewer_id=viewer, target_id=owner, story_id=story_id)
    # learn & adjust
    cats = (await db.users.find_one({"user_id":owner}))["profile_signature"]["category"]
    for c in cats: await update_behavioral_tags((await db.users.find_one({"user_id":viewer}))["profile_signature"], c, "view")
    await adjust_profile_score(db, owner, ACTION_WEIGHTS["view"])
    await delete_cache(f"recommendations:{viewer}")
    return {"status":"view recorded"}

@router.post("/skip/{target_id}")
async def skip_user(target_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.mongodb; viewer=current_user["user_id"]
    u = await db.users.find_one({"user_id":target_id}); 
    if not u: raise HTTPException(404,"User not found")
    for c in u["profile_signature"]["category"]:
        await update_behavioral_tags((await db.users.find_one({"user_id":viewer}))["profile_signature"], c, "skip")
    await adjust_profile_score(db, target_id, ACTION_WEIGHTS["skip"])
    await delete_cache(f"recommendations:{viewer}")
    return {"status":"skip recorded"}

@router.post("/react/{story_id}")
async def react_story(story_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    db: AsyncIOMotorClient = request.app.mongodb
    viewer=current_user["user_id"]
    doc = await db.stories.find_one({"stories.story_id":story_id})
    if not doc: raise HTTPException(404,"Story not found")
    owner=doc["_id"]
    # create snapshot
    story = next(s for s in doc["stories"] if s["story_id"]==story_id)
    from db.models.stories import EmbedSnapshot, Reaction
    snap=EmbedSnapshot(
        story_id=story_id,author_id=owner,
        thumbnail_url=story["details"]["content_url"],
        content_type=story["details"]["content_type"],
        caption=story["details"].get("caption"),timestamp=datetime.utcnow()
    )
    reaction=Reaction(user_id=viewer,reaction_story=snap)
    await db.stories.update_one(
        {"_id":owner,"stories.story_id":story_id},
        {"$push":{"stories.$.reactions":reaction.model_dump()}}
    )
    # learn & adjust
    cats=(await db.users.find_one({"user_id":owner}))["profile_signature"]["category"]
    for c in cats: await update_behavioral_tags((await db.users.find_one({"user_id":viewer}))["profile_signature"], c, "react")
    await adjust_profile_score(db, owner, ACTION_WEIGHTS["react"])
    await delete_cache(f"recommendations:{viewer}")
    return {"status":"reaction recorded"}

@router.post("/share/{story_id}")
async def share_story(story_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    db=request.app.mongodb; viewer=current_user["user_id"]
    doc = await db.stories.find_one({"stories.story_id":story_id})
    if not doc: raise HTTPException(404,"Story not found")
    owner=doc["_id"]
    await db.stories.update_one(
        {"_id":owner,"stories.story_id":story_id},
        {"$push":{"stories.$.shares":{"user_id":viewer,"platform":"app","shared_at":datetime.utcnow()}}}
    )
    cats=(await db.users.find_one({"user_id":owner}))["profile_signature"]["category"]
    for c in cats: await update_behavioral_tags((await db.users.find_one({"user_id":viewer}))["profile_signature"], c, "share")
    await adjust_profile_score(db, owner, ACTION_WEIGHTS["share"])
    await delete_cache(f"recommendations:{viewer}")
    return {"status":"share recorded"}

@router.post("/repost/{story_id}")
async def repost_story(story_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    db=request.app.mongodb; viewer=current_user["user_id"]
    doc = await db.stories.find_one({"stories.story_id":story_id})
    if not doc: raise HTTPException(404,"Story not found")
    owner=doc["_id"]
    story = next(s for s in doc["stories"] if s["story_id"]==story_id)
    from db.models.stories import EmbedSnapshot, Repost
    snap=EmbedSnapshot(
        story_id=story_id,author_id=owner,
        thumbnail_url=story["details"]["content_url"],
        content_type=story["details"]["content_type"],
        caption=story["details"].get("caption"),timestamp=datetime.utcnow()
    )
    repost=Repost(user_id=viewer,repost_story=snap)
    await db.stories.update_one(
        {"_id":owner,"stories.story_id":story_id},
        {"$push":{"stories.$.reposts":repost.model_dump()}}
    )
    cats=(await db.users.find_one({"user_id":owner}))["profile_signature"]["category"]
    for c in cats: await update_behavioral_tags((await db.users.find_one({"user_id":viewer}))["profile_signature"], c, "repost")
    await adjust_profile_score(db, owner, ACTION_WEIGHTS["repost"])
    await delete_cache(f"recommendations:{viewer}")
    return {"status":"repost recorded"}
