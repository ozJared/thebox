from db.models.users import UserModel
from db.models.stories import UserPreview
from motor.motor_asyncio import AsyncIOMotorClient
import jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from bson import ObjectId
from fastapi import HTTPException, FastAPI
from bson.errors import InvalidId
from typing import List
from passlib.context import CryptContext
from datetime import datetime

from db.redis_client import PROFILE_CACHE_TTL, delete_cache, get_cache, set_cache


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

async def create_user(db: AsyncIOMotorClient, user: UserModel):
    # Duplicate check
    if await db.users.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    if await db.users.find_one({"username": user.username}):
        raise HTTPException(status_code=400, detail="Username already taken")

    user_dict = user.model_dump()
    
    # Convert URLs to string
    if user_dict.get("profile_image_url"):
        user_dict["profile_image_url"] = str(user_dict["profile_image_url"])

    for story in user_dict["stories"]:
        if story.get("thumbnail_url"):
            story["thumbnail_url"] = str(story["thumbnail_url"])

    # Hash password
    user_dict["password"] = pwd_context.hash(user_dict["password"])

    user_dict["_id"] = user_dict["user_id"]
    
    await db.users.insert_one(user_dict)

    return {"message": "User created successfully", "user_id": user.user_id}

async def login_user(db, email: str, password: str):
    user = await db.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Incorrect password")

    return {
        "user_id": str(user["_id"]),
        "username": user["username"],
        "email": user["email"],
    }

async def update_refresh_token(db, user_id: str, token: str):
    await db["users"].update_one(
        {"user_id": user_id},
        {"$set": {"refresh_token": token}}
    )

async def remove_refresh_token(db, user_id: str):
    await db["users"].update_one({"user_id": user_id}, {"$unset": {"refresh_token": ""}})



# GET SINGLE USER
from db.redis_client import get_cache, set_cache, PROFILE_CACHE_TTL
from fastapi import HTTPException

async def get_user_by_id(db, user_id: str) -> dict:
    # 1️⃣ Check Redis cache first
    cached = await get_cache(f"user:{user_id}")
    if cached:
        print("🟢 Returned from Redis cache")
        return cached

    # 2️⃣ If not in cache → Fetch from DB
    print("🧠 Fetched from MongoDB")
    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = {
        "user_id": user["_id"],
        "username": user["username"],
        "profile_image_url": user.get("profile_image_url"),
    }

    # 3️⃣ Cache it for future requests
    await set_cache(f"user:{user_id}", user_data, ttl=PROFILE_CACHE_TTL)

    return user_data



# GET ALL USERS (with pagination & safety cap)
async def get_all_users(db, skip: int = 0, limit: int = 10) -> list[dict]:
    limit = min(limit, 100)  # Max 100 per request

    cursor = db.users.find().skip(skip).limit(limit)
    users = await cursor.to_list(length=limit)
    
    return [
        {
            "user_id": user["_id"],
            "username": user["username"],
            "profile_image_url": user.get("profile_image_url")
        }
        for user in users
    ]
    
    
async def update_user_profile(db, user_id: str, update_data: dict):
    # Clean up any URLs
    if update_data.get("profile_image_url"):
        update_data["profile_image_url"] = str(update_data["profile_image_url"])

    update_data["updated_at"] = datetime.utcnow()

    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": update_data}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found or no change")
    
    await delete_cache(f"user:{user_id}")

    return {"message": "User updated successfully"}


async def delete_user_account(db, user_id: str):
    result = await db.users.delete_one({"user_id": user_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # Optional: remove their stories too
    await db.stories.delete_many({"user.user_id": user_id})
    await delete_cache(f"user:{user_id}")

    return {"message": "User and stories deleted successfully"}
