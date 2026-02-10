from __future__ import annotations

import json
from typing import Any, List, Dict

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite database file (created where uvicorn runs from)
DATABASE_URL = "sqlite:///./thesis_recom.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ----------------------------
# JSON helper functions
# ----------------------------

def _json_dump(values: Any) -> str:
    """Convert Python object into JSON string."""
    if values is None:
        return "null"
    if isinstance(values, str):
        return values
    return json.dumps(values, ensure_ascii=False)


def _json_load(value: Any, default: Any):
    """Convert JSON string from DB into Python object (or default on failure)."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:
            return default
    return default


def _json_dump_list(values: Any) -> str:
    """Convert list-like object into JSON list string."""
    if values is None:
        return "[]"
    if isinstance(values, str):
        return values
    return json.dumps(list(values), ensure_ascii=False)


def _json_load_list(value: Any) -> List[str]:
    """Convert JSON list string into list[str]. Supports CSV fallback."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
        # CSV fallback (for older DBs)
        return [x.strip() for x in s.split(",") if x.strip()]
    return []


# ----------------------------
# DB models
# ----------------------------

class UserProfile(Base):
    """Stores onboarding answers for each user."""
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    city = Column(String(100), nullable=False)

    tags = Column(Text, nullable=False, default="[]")  # JSON list
    favorite_artists = Column(Text, nullable=False, default="[]")  # JSON list

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def get_tags(self) -> List[str]:
        return _json_load_list(self.tags)

    def set_tags(self, tags_list: List[str]) -> None:
        self.tags = _json_dump_list(tags_list)

    def get_favorite_artists(self) -> List[str]:
        return _json_load_list(self.favorite_artists)

    def set_favorite_artists(self, artists_list: List[str]) -> None:
        self.favorite_artists = _json_dump_list(artists_list)


class Event(Base):
    """Stores events created by admin."""
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("title", "city", "date", name="uq_event_title_city_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    city = Column(String(100), nullable=False)
    date = Column(Date, nullable=False)

    language = Column(String(50), nullable=False)  # greek / english / both
    tags = Column(Text, nullable=False, default="[]")     # JSON list
    artists = Column(Text, nullable=False, default="[]")  # JSON list

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def get_tags(self) -> List[str]:
        return _json_load_list(self.tags)

    def set_tags(self, tags_list: List[str]) -> None:
        self.tags = _json_dump_list(tags_list)

    def get_artists(self) -> List[str]:
        return _json_load_list(self.artists)

    def set_artists(self, artists_list: List[str]) -> None:
        self.artists = _json_dump_list(artists_list)


class RecommenderConfig(Base):
    """Single-row table storing weights used by the recommender."""
    __tablename__ = "recommender_config"

    id = Column(Integer, primary_key=True)
    w_cbf = Column(String(20), nullable=False, default="0.6")
    w_context = Column(String(20), nullable=False, default="0.4")
    max_artist_boost = Column(String(20), nullable=False, default="0.3")
    w_language = Column(String(20), nullable=False, default="0.15")

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class RecommendationLog(Base):
    """Logs each recommendations request for evaluation (upgrade #6)."""
    __tablename__ = "recommendation_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), index=True, nullable=False)
    mode = Column(String(30), nullable=False)  # baseline/hybrid

    date_from = Column(String(20), nullable=True)
    date_to = Column(String(20), nullable=True)
    top_n = Column(Integer, nullable=False, default=10)

    weights_json = Column(Text, nullable=False, default="{}")
    results_json = Column(Text, nullable=False, default="[]")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def set_weights(self, weights: Dict) -> None:
        self.weights_json = _json_dump(weights)

    def set_results(self, results: List[Dict]) -> None:
        self.results_json = _json_dump(results)

    def get_weights(self) -> Dict:
        return _json_load(self.weights_json, {})

    def get_results(self) -> List[Dict]:
        return _json_load(self.results_json, [])


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
