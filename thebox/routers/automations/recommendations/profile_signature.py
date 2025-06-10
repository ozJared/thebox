from collections import defaultdict
from typing import List, Optional
from db.models.users import ProfileSignature
from .categories import CATEGORY_KEYWORDS
import re

# Normalize categories and keywords to lowercase for consistent matching
def _normalize_keywords(mapping):
    return {category.casefold(): [kw.casefold() for kw in keywords]
            for category, keywords in mapping.items()}

CATEGORY_KEYWORDS = _normalize_keywords(CATEGORY_KEYWORDS)


def extract_tags_from_bio(bio: str) -> List[str]:
    tags: List[str] = []
    bio_norm = bio.casefold()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, bio_norm):
                tags.append(keyword)
    return list(set(tags))  # unique, already lowercase


def infer_categories(signature: ProfileSignature) -> List[str]:
    category_scores = defaultdict(int)
    sources = [signature.bio_tags, signature.interests, signature.behavioral_tags]
    for source in sources:
        for tag in source:
            tag_norm = tag.casefold()
            for category, keywords in CATEGORY_KEYWORDS.items():
                if tag_norm in keywords:
                    category_scores[category] += 1
    # Extra weight for behavioral tags
    for tag in signature.behavioral_tags:
        tag_norm = tag.casefold()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if tag_norm in keywords:
                category_scores[category] += 1
    return [cat for cat, score in category_scores.items() if score >= 2]


def generate_profile_signature(user: dict) -> ProfileSignature:
    bio = user.get("bio", "")
    location = user.get("location")
    interests = [i.casefold() for i in user.get("interests", [])]
    bio_tags = extract_tags_from_bio(bio)

    signature = ProfileSignature(
        category=[],
        interests=interests,
        bio_tags=bio_tags,
        behavioral_tags=[],
        location=location,
        category_test={},
        profile_score=50
    )
    signature.category = infer_categories(signature)
    return signature


def matching_tags(signature: ProfileSignature) -> List[str]:
    counts = defaultdict(int)
    sources = [signature.behavioral_tags, signature.interests, signature.bio_tags]
    if signature.category:
        sources.append(signature.category)
    for source in sources:
        for tag in source:
            counts[tag.casefold()] += 1
    sorted_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [tag for tag, _ in sorted_tags]


def update_behavioral_tags(signature: dict, category: str, action: str) -> dict:
    weights = {"view": 1, "react": 2, "repost": 2, "share": 3, "skip": -2}
    score = weights.get(action, 0)
    signature.setdefault("category_test", {})
    signature.setdefault("behavioral_tags", [])
    signature["category_test"][category] = max(0, signature["category_test"].get(category, 0) + score)
    if signature["category_test"][category] >= 5 and category not in signature["behavioral_tags"]:
        signature["behavioral_tags"].append(category)
    if signature["category_test"][category] < 2 and category in signature["behavioral_tags"]:
        signature["behavioral_tags"].remove(category)
    return signature