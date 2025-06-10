import json
from fastapi import APIRouter, Request, HTTPException, Depends, Query, Body, UploadFile, File, Form
from fastapi.security import OAuth2PasswordRequestForm
from typing import List, Optional
from datetime import datetime
import os

from pydantic import BaseModel
from db.models.users import ProfileSignature, UserModel, UserInput
from db.models.stories import TextStoryInput, UserPreview, Story, StoryInput
from routers.crud.users import (
    create_user, get_user_by_id, get_all_users, login_user,
    update_refresh_token, remove_refresh_token,
    update_user_profile, delete_user_account
)
from routers.crud.stories import (
    create_media_story, create_text_story, get_stories_by_user_id, track_story_view,
    update_story, delete_story
)

from security.main import (
    create_access_token, create_refresh_token,
    decode_access_token
)
from security.dependencies import get_current_user
from db.redis_client import get_cache, redis_client, set_cache

from uuid import uuid4

from routers.automations.recommendations.profile_signature import generate_profile_signature, infer_categories
from routers.automations.recommendations.recommender import recommend_users, recommend_users_from_signature

router = APIRouter(prefix="/users", tags=["Users"])
test_router = APIRouter(prefix="/test", tags=["Redis Test"])
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

@test_router.get("/cache")
async def test_redis_cache():
    key = "greeting"
    cached = redis_client.get(key)

    if cached:
        return {"message": f"From Redis Cache: {cached}"}

    # If not cached, store a new value
    value = "Hello from Redis!"
    redis_client.set(key, value, ex=60)  # Cache expires in 60 seconds
    return {"message": f"Newly Cached: {value}"}



# ------------------ ✅ AUTH ------------------ #

@router.post("/register/")
async def register_user(user_input: UserInput, request: Request):
    db = request.app.mongodb
    # Generate normalized signature
    profile_sig = generate_profile_signature(user_input.model_dump())
    user = UserModel(
        username=user_input.username,
        full_name=user_input.full_name,
        email=user_input.email,
        phone_number=user_input.phone_number,
        password=user_input.password,
        bio=user_input.bio,
        profile_image_url=user_input.profile_image_url,
        age=user_input.age,
        is_verified=False,
        is_online=False,
        signup_platform=user_input.signup_platform,
        joined_at=datetime.utcnow(),
        updated_at=None,
        Stories=[],
        profile_signature=profile_sig,
    )
    return await create_user(db, user)



@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    db = request.app.mongodb
    user = await login_user(db, form_data.username, form_data.password)

    payload = {
        "user_id": user["user_id"],
        "username": user["username"],
        "profile_image_url": user.get("profile_image_url")
    }

    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)

    await update_refresh_token(db, user["user_id"], refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user
    }


@router.post("/refresh")
async def refresh_token(request: Request, refresh_token: str):
    db = request.app.mongodb

    try:
        payload = decode_access_token(refresh_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    user = await db["users"].find_one({"user_id": payload.get("user_id")})
    if not user or user.get("refresh_token") != refresh_token:
        raise HTTPException(status_code=403, detail="Invalid refresh token")

    # ✅ Issue new tokens
    access = create_access_token(payload)
    new_refresh = create_refresh_token(payload)
    await update_refresh_token(db, user["user_id"], new_refresh)

    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "token_type": "bearer"
    }


@router.post("/logout")
async def logout(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.mongodb
    await remove_refresh_token(db, current_user["user_id"])
    return {"message": "Logged out successfully"}


# ------------------ ✅ USERS ------------------ #

@router.get("/get_users/users/{user_id}", response_model=UserPreview)
async def handle_get_user(user_id: str, request: Request):
    db = request.app.mongodb
    return await get_user_by_id(db, user_id)


@router.get("/get_users/users", response_model=List[UserPreview])
async def handle_get_all_users(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100)
):
    db = request.app.mongodb
    return await get_all_users(db, skip=skip, limit=limit)


@router.put("/update_user")
async def update_profile(
    request: Request,
    update: dict = Body(...),
    current_user: dict = Depends(get_current_user)
):
    db = request.app.mongodb
    return await update_user_profile(db, current_user["user_id"], update)


@router.delete("/delete")
async def delete_profile(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.mongodb
    return await delete_user_account(db, current_user["user_id"])


# ------------------ ✅ STORIES ------------------ #

@router.post("/stories/text/")
async def post_text_story(
    request: Request,
    input: TextStoryInput,
    current_user: dict = Depends(get_current_user)
):
    db = request.app.mongodb
    return await create_text_story(
        db=db,
        request=request,
        current_user=current_user,
        caption=input.caption,
        mentions=input.mentions
    )


### B) Media Story Route
@router.post("/stories/media/")
async def post_media_story(
    request: Request,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    mentions: Optional[str] = Form("[]"),  # JSON‐encoded list
    current_user: dict = Depends(get_current_user)
):
    db = request.app.mongodb

    # Parse JSON list of mentions
    try:
        mention_list = json.loads(mentions)
        if not isinstance(mention_list, list):
            mention_list = []
    except:
        mention_list = []

    return await create_media_story(
        db=db,
        request=request,
        current_user=current_user,
        file=file,
        caption=caption,
        mentions=mention_list
    )



@router.get("/stories/user/{user_id}")
async def get_user_stories(user_id: str, request: Request):
    db = request.app.mongodb
    return await get_stories_by_user_id(db, user_id)


@router.put("/stories/{story_id}")
async def update_user_story(
    story_id: str,
    update: dict,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    db = request.app.mongodb

    # Uses user_id as the document's _id in `stories` collection
    return await update_story(db, story_id, current_user["user_id"], update)



@router.delete("/stories/{story_id}")
async def delete_user_story(
    story_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    db = request.app.mongodb
    return await delete_story(db, story_id, current_user["user_id"])


# ------------------ ✅ Recommend users ------------------ #

class PublicExploreInput(BaseModel):
    interests: List[str]
    location: Optional[str] = None

@router.post("/public/", response_model=List[dict])
async def explore_without_login(payload: PublicExploreInput, request: Request):
    db = request.app.mongodb
    cache_key = f"public:{'-'.join(sorted(payload.interests or []))}:{payload.location or 'any'}"

    # 1️⃣ Try Redis cache first
    cached = await get_cache(cache_key)
    if cached:
        return cached

    # 2️⃣ Normalize interests (lowercase)
    interests = [i.lower() for i in payload.interests or []]

    # 3️⃣ Build mock ProfileSignature
    signature = ProfileSignature(
        interests=interests,
        behavioral_tags=interests,
        bio_tags=[],
        location=payload.location,
        category=[],        # will be inferred below
        category_test={},
        profile_score=50
    )

    # 4️⃣ Infer umbrella categories
    signature.category = infer_categories(signature)

    # 5️⃣ Get recommendations
    matches = await recommend_users_from_signature(db, signature)

    # 6️⃣ Fallback if no match
    if not matches:
        fallback = await db.users.find(
            {"profile_signature": {"$exists": True}}
        ).sort("profile_signature.profile_score", -1).limit(10).to_list(10)

        matches = [{
            "user_id": u["user_id"],
            "username": u.get("username"),
            "profile_image_url": u.get("profile_image_url"),
            "score": u.get("profile_signature", {}).get("profile_score", 50),
            "reason": "Top users in system"
        } for u in fallback]

    # 7️⃣ Cache & return
    await set_cache(cache_key, matches, ttl=3600)
    return matches

@router.get("/recommendations")
async def get_recommendation_list(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.mongodb
    return await recommend_users(db, current_user)

@router.post("/stories/viewed/{target_id}")
async def mark_stories_viewed(
    target_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    db = request.app.mongodb
    await track_story_view(db, viewer_id=current_user["user_id"], target_id=target_id)
    return {"status": "marked as seen"}
