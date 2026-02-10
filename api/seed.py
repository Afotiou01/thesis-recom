from __future__ import annotations

from datetime import date
from sqlalchemy.exc import IntegrityError

from database import SessionLocal, Event, RecommenderConfig


def seed() -> None:
    """Seed default weights + a sample event (safe to run multiple times)."""
    db = SessionLocal()
    try:
        cfg = db.query(RecommenderConfig).first()
        if not cfg:
            cfg = RecommenderConfig(
                w_cbf="0.6",
                w_context="0.4",
                max_artist_boost="0.3",
                w_language="0.15",
            )
            db.add(cfg)
            db.commit()

        sample = [
            {
                "title": "Limassol Rock Festival",
                "city": "Limassol",
                "date": date(2026, 3, 10),
                "language": "english",
                "tags": ["concert", "lang_english", "rock", "live", "festival"],
                "artists": ["Imagine Dragons", "Arctic Monkeys"],
            },
        ]

        for item in sample:
            ev = Event(
                title=item["title"],
                city=item["city"],
                date=item["date"],
                language=item["language"],
            )
            ev.set_tags(item["tags"])
            ev.set_artists(item["artists"])

            db.add(ev)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
    finally:
        db.close()
