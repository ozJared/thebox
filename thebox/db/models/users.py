from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator
from typing import Dict, Optional, List
from datetime import datetime
from enum import Enum
from db.models.stories import EmbedSnapshot
from uuid import uuid4

class ContentType(str, Enum):
    image = "image"
    video = "video"
    audio = "audio"
    text = "text"

class SignupPlatform(str, Enum):
    facebook = "facebook"
    google = "google"
    tiktok = "tiktok"
    x = "x"
    twitch = "twitch"
    linkedin = "linkedin"
    instagram = "instagram"
    unknown = "unknown"
    
class WatchedStory(BaseModel):
    viewer_id: str
    target_id: str
    stories: List[EmbedSnapshot] = Field(default_factory=list)
    last_seen_story_id: str
    all_seen = True
    last_seen: datetime = Field(default_factory=datetime.utcnow)

class ViewerLog(BaseModel):
    target_id: str
    viewers: List[str] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

class StoryReference(BaseModel):
    story_id: str
    user_id: str
    content_type: ContentType
    thumbnail_url: Optional[HttpUrl]
    created_at: datetime
    
class ProfileSignature(BaseModel):
    category: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    bio_tags: List[str] = Field(default_factory=list)
    behavioral_tags: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    category_test: dict = Field(default_factory=dict)
    profile_score: int = 50


class UserInput(BaseModel):
    username: str = Field(..., pattern=r'^[a-zA-Z0-9_]+$', min_length=3, max_length=50)
    full_name: Optional[str] = Field(None, max_length=100)
    email: EmailStr
    phone_number: Optional[str] = Field(None, min_length=10, max_length=16)
    password: str = Field(..., min_length=8)
    bio: Optional[str] = Field(None, max_length=2000)
    profile_image_url: Optional[HttpUrl] = None
    age: Optional[int] = Field(None, ge=13)
    signup_platform: Optional[SignupPlatform] = SignupPlatform.unknown
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, value):
        if len(value) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if value.isdigit() or value.isalpha():
            raise ValueError('Password must contain both letters and numbers')
        return value

    @field_validator('username')
    @classmethod
    def validate_username(cls, value):
        if ' ' in value:
            raise ValueError('Username cannot contain spaces')
        return value

    @field_validator('phone_number')
    @classmethod
    def validate_phone_number(cls, value):
        if value and not value.isdigit():
            raise ValueError('Phone number must contain only digits')
        return value


class UserModel(BaseModel):
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    username: str = Field(..., pattern=r'^[a-zA-Z0-9_]+$', min_length=3, max_length=50)
    full_name: Optional[str] = Field(None, max_length=100)
    email: EmailStr
    phone_number: Optional[str] = Field(None, min_length=10, max_length=16)
    password: str = Field(..., min_length=8)
    bio: Optional[str] = Field(None, max_length=2000)
    profile_image_url: Optional[HttpUrl] = None
    age: Optional[int]
    is_verified: bool = False
    is_online: bool = False
    signup_platform: SignupPlatform = SignupPlatform.unknown
    joined_at: datetime
    updated_at: Optional[datetime] = None
    refresh_token: Optional[str] = None
    profile_signature: ProfileSignature = Field(
        default_factory=ProfileSignature,
        description="Dynamic signature summarizing who this user is."
    )
    stories: List[StoryReference] = Field(default_factory=list)
    last_seen_stories: List[str] = Field(default_factory=list)


    @field_validator('password')
    @classmethod
    def validate_password(cls, value):
        if len(value) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if value.isdigit() or value.isalpha():
            raise ValueError('Password must contain both letters and numbers')
        return value

    @field_validator('phone_number')
    @classmethod
    def validate_phone_number(cls, value):
        if value and not value.isdigit():
            raise ValueError('Phone number must contain only digits')
        return value



