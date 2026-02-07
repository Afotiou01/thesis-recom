# this file runs the FastAPI server and exposes endpoints for:
# - user profile creation
# - admin event creation
# - recommendations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from .database import SessionLocal, init_db, UserProfile, Event
from .recommender import parse_csv, in_date_window, score_event
from .seed import seed

app = FastAPI(title="thesis-recom API")

# allow frontend pages to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# fixed tag options used by admin + user UI
TAG_OPTIONS = [
    "concert",
    "lang_greek",
    "lang_english",
    "laiko",
    "entehno",
    "rebetiko",
    "greek_pop",
    "greek_rock",
    "rock",
    "pop",
    "indie",
    "alternative",
    "metal",
    "jazz",
    "soul",
    "rnb",
    "electronic",
    "edm",
    "techno",
    "house",
    "latin",
    "reggaeton",
    "reggae",
    "classical",
    "acoustic",
    "instrumental",
    "live",
    "festival",
    "club",
]


@app.on_event("startup")
def startup():
    # this runs when the API starts
    init_db()
    seed()


class UserCreate(BaseModel):
    # this model defines what the onboarding form sends
    username: str
    city: str
    tags: List[str]
    favorite_artists: List[str]


class EventCreate(BaseModel):
    # this model defines what the admin form sends
    title: str
    city: str
    date: str
    language: str
    tags: List[str]
    artists: List[str]


@app.get("/tag-options")
def get_tag_options():
    # this endpoint returns available tags for dropdowns/checkboxes
    return {"tags": TAG_OPTIONS}


@app.get("/artist-options")
def get_artist_options():
    # this endpoint returns unique artists from current events (sorted)
    db = SessionLocal()
    try:
        events = db.query(Event).all()
        artists = set()
        for ev in events:
            for a in parse_csv(ev.artists):
                artists.add(a)
        return {"artists": sorted(artists, key=lambda x: x.lower())}
    finally:
        db.close()


@app.post("/admin/add-event")
def add_event(ev: EventCreate):
    # this endpoint stores a new event in db
    db = SessionLocal()
    try:
        new_ev = Event(
            title=ev.title,
            city=ev.city,
            date=ev.date,
            language=ev.language,
            tags=",".join(ev.tags),
            artists=",".join(ev.artists),
        )
        db.add(new_ev)
        db.commit()
        db.refresh(new_ev)
        return {"status": "ok", "event_id": new_ev.id}
    finally:
        db.close()


@app.post("/user/save-profile")
def save_profile(u: UserCreate):
    # this endpoint stores (or updates) the user profile in db
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter(UserProfile.username == u.username).first()
        if not profile:
            profile = UserProfile(username=u.username)
            db.add(profile)

        profile.city = u.city
        profile.tags = ",".join(u.tags)
        profile.favorite_artists = ",".join(u.favorite_artists)

        db.commit()
        return {"status": "ok"}
    finally:
        db.close()


@app.get("/recommendations")
def recommendations(
    username: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    top_n: int = 10
):
    # this endpoint returns the ranked events for a user
    db = SessionLocal()
    try:
        user = db.query(UserProfile).filter(UserProfile.username == username).first()
        if not user:
            return {"status": "error", "message": "User not found", "results": []}

        user_tags = parse_csv(user.tags)
        user_city = user.city
        user_artists = parse_csv(user.favorite_artists)

        events = db.query(Event).all()

        # filter by date first
        eligible = [ev for ev in events if in_date_window(ev.date, date_from, date_to)]

        scored = [score_event(user_tags, user_city, user_artists, ev) for ev in eligible]
        scored.sort(key=lambda x: x["score"], reverse=True)

        return {"status": "ok", "count": min(top_n, len(scored)), "results": scored[:top_n]}
    finally:
        db.close()
