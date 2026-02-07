# this file contains the scoring logic (CBF + Context + Artist boost)

from datetime import datetime
from typing import List, Dict

# weights
W_CBF = 0.6
W_CONTEXT = 0.4
MAX_ARTIST_BOOST = 0.3

# distance-like convenience scores for Cyprus (simple demo matrix)
CITY_DISTANCE_SCORES = {
    "nicosia": {"nicosia": 1.0, "larnaca": 0.7, "limassol": 0.6, "paphos": 0.4},
    "larnaca": {"larnaca": 1.0, "nicosia": 0.7, "limassol": 0.7, "paphos": 0.5},
    "limassol": {"limassol": 1.0, "paphos": 0.8, "larnaca": 0.6, "nicosia": 0.4},
    "paphos": {"paphos": 1.0, "limassol": 0.8, "larnaca": 0.5, "nicosia": 0.3},
}


def parse_csv(text: str) -> List[str]:
    # this function turns comma separated values into a list
    if not text:
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def jaccard_similarity(user_tags: List[str], event_tags: List[str]) -> float:
    # this function calculates tag similarity using Jaccard
    # J(A,B) = |A ∩ B| / |A ∪ B|
    if not user_tags or not event_tags:
        return 0.0

    u = set(t.lower() for t in user_tags)
    e = set(t.lower() for t in event_tags)

    inter = u.intersection(e)
    union = u.union(e)

    if not union:
        return 0.0

    return len(inter) / len(union)


def compute_context_score(event_city: str, user_city: str) -> float:
    # this function calculates the context score based on the city matrix
    if not event_city or not user_city:
        return 0.0

    ec = event_city.strip().lower()
    uc = user_city.strip().lower()

    row = CITY_DISTANCE_SCORES.get(uc)
    loc = 0.3  # default fallback

    if row and ec in row:
        loc = row[ec]

    date_score = 1.0  # date filtering is done before scoring
    return (loc + date_score) / 2.0


def compute_artist_boost(user_artists: List[str], event_artists: List[str]) -> float:
    # this function adds bonus score if favorite artists match
    if not user_artists or not event_artists:
        return 0.0

    u = set(a.lower() for a in user_artists)
    e = set(a.lower() for a in event_artists)

    overlap = [a for a in u if a in e]
    if not overlap:
        return 0.0

    overlap_ratio = len(overlap) / len(u)
    boost = MAX_ARTIST_BOOST * overlap_ratio
    return min(boost, MAX_ARTIST_BOOST)


def in_date_window(event_date: str, date_from: str | None, date_to: str | None) -> bool:
    # this function checks if event is inside date range (and not in the past)
    try:
        d = datetime.strptime(event_date, "%Y-%m-%d").date()
    except Exception:
        return False

    today = datetime.today().date()
    if d < today:
        return False

    if date_from:
        f = datetime.strptime(date_from, "%Y-%m-%d").date()
        if d < f:
            return False

    if date_to:
        t = datetime.strptime(date_to, "%Y-%m-%d").date()
        if d > t:
            return False

    return True


def score_event(user_tags, user_city, user_artists, event) -> Dict:
    # this function produces final score + breakdown
    ev_tags = parse_csv(event.tags)
    ev_artists = parse_csv(event.artists)

    cbf = jaccard_similarity(user_tags, ev_tags)
    context = compute_context_score(event.city, user_city)
    artist_boost = compute_artist_boost(user_artists, ev_artists)

    score = W_CBF * cbf + W_CONTEXT * context + artist_boost
    score = max(0.0, min(1.0, score))

    return {
        "id": event.id,
        "title": event.title,
        "city": event.city,
        "date": event.date,
        "language": event.language,
        "tags": ev_tags,
        "artists": ev_artists,
        "score": round(score, 3),
        "breakdown": {
            "cbf": round(cbf, 3),
            "context": round(context, 3),
            "artist_boost": round(artist_boost, 3),
            "weights": {"W_CBF": W_CBF, "W_CONTEXT": W_CONTEXT, "MAX_ARTIST_BOOST": MAX_ARTIST_BOOST}
        }
    }
