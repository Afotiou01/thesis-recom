from __future__ import annotations

import random
from datetime import date
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict

from database import (
    SessionLocal,
    init_db,
    UserProfile,
    Event,
    RecommenderConfig,
    RecommendationLog,
)
from recommender import in_date_window, score_event
from seed import seed

app = FastAPI(title="Thesis-Recom API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------
# DB dependency
# ----------------------------

def get_db():
    """Provide a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _clean_list(values: List[str]) -> List[str]:
    """Trim, remove empty entries, deduplicate case-insensitively."""
    seen = set()
    out = []
    for v in values or []:
        s = (v or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _get_cfg(db) -> RecommenderConfig:
    """Ensure there is a config row and return it."""
    cfg = db.query(RecommenderConfig).first()
    if not cfg:
        cfg = RecommenderConfig(w_cbf="0.6", w_context="0.4", max_artist_boost="0.3", w_language="0.15")
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def interleave_random(
    ranked: list[dict],
    random_pool: list[dict],
    top_n: int,
    random_every: int = 5,
    random_count: int = 1,
    seed_key: str = "",
) -> list[dict]:
    """
    Diversification strategy:
      Take `random_every` ranked items then insert `random_count` random items from random_pool, repeating.
    """
    if top_n <= 0:
        return []

    rnd = random.Random(seed_key)  # stable randomness per request (reproducible)
    ranked_copy = ranked[:]
    pool_copy = random_pool[:]
    rnd.shuffle(pool_copy)

    out: list[dict] = []
    i = 0

    while len(out) < top_n and (i < len(ranked_copy) or pool_copy):
        for _ in range(random_every):
            if len(out) >= top_n or i >= len(ranked_copy):
                break
            out.append(ranked_copy[i])
            i += 1

        for _ in range(random_count):
            if len(out) >= top_n:
                break
            if not pool_copy:
                break
            out.append(pool_copy.pop())

    return out


@app.on_event("startup")
def startup():
    """Create tables and seed initial data."""
    init_db()
    seed()


# ----------------------------
# Pydantic request models
# ----------------------------

class UserCreate(BaseModel):
    """Payload from onboarding form."""
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., min_length=1, max_length=100)
    city: str = Field(..., min_length=1, max_length=100)
    tags: List[str] = Field(default_factory=list)
    favorite_artists: List[str] = Field(default_factory=list)


class EventCreate(BaseModel):
    """Payload from admin add-event form."""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    date: date
    language: str = Field(..., min_length=1, max_length=50)
    tags: List[str] = Field(default_factory=list)
    artists: List[str] = Field(default_factory=list)


class WeightsUpdate(BaseModel):
    """Payload to update weights from frontend sliders."""
    model_config = ConfigDict(extra="forbid")
    w_cbf: float = Field(..., ge=0.0, le=1.0)
    w_context: float = Field(..., ge=0.0, le=1.0)
    max_artist_boost: float = Field(..., ge=0.0, le=1.0)
    w_language: float = Field(..., ge=0.0, le=1.0)


# ----------------------------
# Dynamic options (DB-driven UI)
# ----------------------------

@app.get("/options")
def get_dynamic_options(db=Depends(get_db)):
    """
    Return cities/tags/artists that are currently present in the DB.
    Frontend uses this so dropdowns reflect real data only.
    """
    events = db.query(Event).all()

    tags = set()
    artists = set()
    cities = set()
    languages = set()

    for ev in events:
        cities.add(ev.city)
        languages.add((ev.language or "").strip().lower())
        for t in ev.get_tags():
            if t:
                tags.add(t)
        for a in ev.get_artists():
            if a:
                artists.add(a)

    # used by UI to hide Greek-only genres when English is selected
    greek_only_tags = {"laiko", "entehno", "rebetiko", "greek_pop", "greek_rock", "lang_greek"}
    english_only_tags = {"lang_english"}

    return {
        "cities": sorted(cities, key=lambda x: x.lower()),
        "tags": sorted(tags, key=lambda x: x.lower()),
        "artists": sorted(artists, key=lambda x: x.lower()),
        "tag_groups": {"greek_only": sorted(greek_only_tags), "english_only": sorted(english_only_tags)},
        "languages_present": sorted(languages),
    }


# ----------------------------
# Weights endpoints
# ----------------------------

@app.get("/config/weights")
def get_weights(db=Depends(get_db)):
    """Return current persisted weights."""
    cfg = _get_cfg(db)
    return {
        "w_cbf": float(cfg.w_cbf),
        "w_context": float(cfg.w_context),
        "max_artist_boost": float(cfg.max_artist_boost),
        "w_language": float(cfg.w_language),
    }


@app.put("/config/weights")
def set_weights(payload: WeightsUpdate, db=Depends(get_db)):
    """Update weights. Enforces w_cbf + w_context = 1.0."""
    if abs((payload.w_cbf + payload.w_context) - 1.0) > 1e-6:
        raise HTTPException(status_code=400, detail="w_cbf + w_context must equal 1.0")

    cfg = _get_cfg(db)
    cfg.w_cbf = str(payload.w_cbf)
    cfg.w_context = str(payload.w_context)
    cfg.max_artist_boost = str(payload.max_artist_boost)
    cfg.w_language = str(payload.w_language)
    db.commit()
    return {"status": "ok"}


# ----------------------------
# Admin endpoints
# ----------------------------

@app.post("/admin/events", status_code=status.HTTP_201_CREATED)
def add_event(ev: EventCreate, db=Depends(get_db)):
    """Create and persist a new event in SQLite."""
    tags = _clean_list(ev.tags)
    artists = _clean_list(ev.artists)

    new_ev = Event(
        title=ev.title.strip(),
        city=ev.city.strip(),
        date=ev.date,
        language=ev.language.strip().lower(),
    )
    new_ev.set_tags(tags)
    new_ev.set_artists(artists)

    db.add(new_ev)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Could not create event (maybe duplicate).")

    db.refresh(new_ev)
    return {"status": "ok", "event_id": new_ev.id}


@app.post("/users/profile")
def save_profile(u: UserCreate, db=Depends(get_db)):
    """Create or update a user profile."""
    tags = _clean_list(u.tags)
    fav_artists = _clean_list(u.favorite_artists)

    username = u.username.strip()
    profile = db.query(UserProfile).filter(UserProfile.username == username).first()
    if not profile:
        profile = UserProfile(username=username, city=u.city.strip())
        db.add(profile)

    profile.city = u.city.strip()
    profile.set_tags(tags)
    profile.set_favorite_artists(fav_artists)

    db.commit()
    return {"status": "ok"}


@app.get("/events")
def list_events(db=Depends(get_db)):
    """List all events (useful for debugging/admin verification)."""
    events = db.query(Event).order_by(Event.date.asc()).all()
    return {
        "count": len(events),
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "city": e.city,
                "date": e.date.isoformat(),
                "language": e.language,
                "tags": e.get_tags(),
                "artists": e.get_artists(),
            }
            for e in events
        ],
    }


# ----------------------------
# Recommendations endpoint
# ----------------------------

@app.get("/recommendations")
def recommendations(
    username: str = Query(..., min_length=1, max_length=100),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    top_n: int = Query(10, ge=1, le=50),
    mode: str = Query("hybrid", pattern="^(hybrid|baseline)$"),

    # Diversification (exploration)
    diversify: bool = Query(False),
    random_every: int = Query(5, ge=1, le=20),
    random_count: int = Query(1, ge=1, le=5),

    db=Depends(get_db),
):
    """
    Return ranked recommendations for a user.

    - mode=baseline: CBF only (A/B test)
    - mode=hybrid: CBF + Context + Artist boost + Language term
    - diversify=true: interleave random events after every N ranked events
    - logs every request to recommendation_logs
    """
    user = db.query(UserProfile).filter(UserProfile.username == username.strip()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_tags = user.get_tags()
    user_city = user.city
    user_artists = user.get_favorite_artists()

    cfg = _get_cfg(db)
    w_cbf = float(cfg.w_cbf)
    w_context = float(cfg.w_context)
    max_artist_boost = float(cfg.max_artist_boost)
    w_language = float(cfg.w_language)

    events = db.query(Event).all()
    eligible = [ev for ev in events if in_date_window(ev.date, date_from, date_to)]

    scored = [
        score_event(
            user_tags, user_city, user_artists, ev,
            mode=mode,
            w_cbf=w_cbf,
            w_context=w_context,
            max_artist_boost=max_artist_boost,
            w_language=w_language,
        )
        for ev in eligible
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)

    if not diversify:
        results = scored[:top_n]
        for r in results:
            r["is_random_insertion"] = False
    else:
        ranked = scored
        # choose random pool from lower half to encourage "surprise"
        mid = max(0, len(ranked) // 2)
        random_pool = ranked[mid:] if len(ranked) > 10 else ranked[:]

        seed_key = f"{username.strip()}|{mode}|{date_from}|{date_to}"
        results = interleave_random(
            ranked=ranked,
            random_pool=random_pool,
            top_n=top_n,
            random_every=random_every,
            random_count=random_count,
            seed_key=seed_key,
        )

        top_ranked_ids = {r["id"] for r in scored[:top_n]}
        for r in results:
            r["is_random_insertion"] = (r["id"] not in top_ranked_ids)

    # Log request (evaluation)
    log = RecommendationLog(
        username=username.strip(),
        mode=mode,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        top_n=top_n,
    )
    log.set_weights({
        "w_cbf": w_cbf,
        "w_context": w_context,
        "max_artist_boost": max_artist_boost,
        "w_language": w_language,
        "diversify": diversify,
        "random_every": random_every,
        "random_count": random_count,
    })
    log.set_results([{"event_id": r["id"], "score": r["score"], "random": r["is_random_insertion"]} for r in results])

    db.add(log)
    db.commit()

    return {
        "status": "ok",
        "mode": mode,
        "diversify": diversify,
        "count": len(results),
        "results": results
    }
