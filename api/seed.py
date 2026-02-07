# this file adds some initial events if database is empty

from database import SessionLocal, Event, init_db

def seed():
    init_db()
    db = SessionLocal()
    try:
        if db.query(Event).first():
            return

        sample = [
            Event(title="Limassol Rock Festival", city="Limassol", date="2026-03-10", language="english",
                  tags="concert,lang_english,rock,live,festival", artists="Imagine Dragons,Arctic Monkeys"),
            Event(title="Nicosia Techno Night", city="Nicosia", date="2026-03-15", language="english",
                  tags="concert,lang_english,electronic,techno,club", artists="Charlotte de Witte"),
            Event(title="Paphos Greek Night", city="Paphos", date="2026-03-20", language="greek",
                  tags="concert,lang_greek,laiko,live", artists="Antonis Remos"),
            Event(title="Larnaca Jazz Evening", city="Larnaca", date="2026-03-22", language="english",
                  tags="concert,lang_english,jazz,soul,live", artists="Local Jazz Quartet"),
        ]
        for e in sample:
            db.add(e)
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    seed()
