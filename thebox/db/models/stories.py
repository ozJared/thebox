from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from datetime import datetime
from uuid import uuid4
from db.models.users import ContentType

# Lightweight reference to the user who created the story
class UserPreview(BaseModel):
    user_id: str = Field(..., description="ID of the user")
    username: str
    profile_pic: Optional[HttpUrl] = None

# Minimal snapshot of a story used inside reactions or reposts
class EmbedSnapshot(BaseModel):
    story_id: str
    author_id: str  # Just user_id
    thumbnail_url: HttpUrl
    content_type: ContentType
    caption: Optional[str] = None
    timestamp: datetime

# Each view logs only the user_id and time
class View(BaseModel):
    user_id: str
    viewer: UserPreview
    viewed_at: datetime = Field(default_factory=datetime.utcnow)

# Reactions attach a story to another story
class Reaction(BaseModel):
    user_id: str
    reaction_story: EmbedSnapshot
    reacted_at: datetime = Field(default_factory=datetime.utcnow)

# Reposts also embed the story snapshot
class Repost(BaseModel):
    user_id: str
    repost_story: EmbedSnapshot
    reposted_at: datetime = Field(default_factory=datetime.utcnow)

# Shares track where a story was shared and by who
class Share(BaseModel):
    user_id: str
    platform: str
    shared_at: datetime = Field(default_factory=datetime.utcnow)

# When creating a story — this is what client sends
class StoryInput(BaseModel):
    content_url: Optional[HttpUrl] = None
    content_type: ContentType
    caption: Optional[str] = Field(default=None, max_length=300)
    mentions: List[str] = Field(default_factory=list)
    
class TextStoryInput(BaseModel):
    caption: Optional[str] = Field(None, max_length=300)
    mentions: List[str] = Field(default_factory=list)

# Full story saved in DB
class Story(BaseModel):
    story_id: str = Field(default_factory=lambda: str(uuid4()))
    user: UserPreview
    details: StoryInput
    views: List[View] = Field(default_factory=list)
    reactions: List[Reaction] = Field(default_factory=list)
    reposts: List[Repost] = Field(default_factory=list)
    shares: List[Share] = Field(default_factory=list)

class StoryDocument(BaseModel):
    user: UserPreview
    stories: List[Story] = Field(default_factory=list)
