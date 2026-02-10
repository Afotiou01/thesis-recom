from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Simple Cyprus proximity matrix for demo context scoring
CITY_DISTANCE_SCORES = {
    "nicosia": {"nicosia": 1.0, "larnaca": 0.7, "limassol": 0.6, "paphos": 0.4},
    "larnaca": {"larnaca": 1.0, "nicosia": 0.7, "limassol": 0.7, "paphos": 0.5},
    "limassol": {"limassol": 1.0, "paphos": 0.8, "larnaca": 0.6, "nicosia": 0.4},
    "paphos": {"paphos": 1.0, "limassol": 0.8, "larnaca": 0.5, "nicosia": 0.3},
}


def _to_date(value: Any) -> Optional[date]:
    """Convert value into date object (supports date/datetime/YYYY-MM-DD string)."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except Exception:
            return None
    return None


def normalize_list(values: Any) -> List[str]:
    """Normalize values into unique list[str], removing duplicates case-insensitively."""
    if values is None:
        return []
    if isinstance(values, str):
        raw = [x.strip() for x in values.split(",") if x.strip()]
    elif isinstance(values, (list, tuple, set)):
        raw = [str(x).strip() for x in values if str(x).strip()]
    else:
        raw = [str(values).strip()] if str(values).strip() else []

    seen = set()
    out = []
    for v in raw:
        k = v.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
    return out


def jaccard_similarity(user_tags: Sequence[str], event_tags: Sequence[str]) -> float:
    """CBF similarity using Jaccard: |A∩B| / |A∪B|."""
    if not user_tags or not event_tags:
        return 0.0
    u = {t.lower() for t in user_tags if t}
    e = {t.lower() for t in event_tags if t}
    if not u or not e:
        return 0.0
    inter = u.intersection(e)
    union = u.union(e)
    return (len(inter) / len(union)) if union else 0.0


def compute_city_score(event_city: str, user_city: str) -> float:
    """City proximity score from matrix; fallback to 0.3 when unknown."""
    if not event_city or not user_city:
        return 0.3
    ec = event_city.strip().lower()
    uc = user_city.strip().lower()
    row = CITY_DISTANCE_SCORES.get(uc)
    if row and ec in row:
        return float(row[ec])
    return 0.3


def compute_context_score(event_city: str, user_city: str) -> float:
    """
    Context score = average(city proximity, date score).
    Date score is 1.0 because date filtering is handled before scoring.
    """
    city_score = compute_city_score(event_city, user_city)
    date_score = 1.0
    return (city_score + date_score) / 2.0


def compute_artist_boost(user_artists: Sequence[str], event_artists: Sequence[str], max_artist_boost: float) -> float:
    """Bonus based on favourite artist overlap; capped by max_artist_boost."""
    if not user_artists or not event_artists:
        return 0.0

    u = {a.lower() for a in user_artists if a}
    e = {a.lower() for a in event_artists if a}
    if not u or not e:
        return 0.0

    overlap = len(u.intersection(e))
    if overlap == 0:
        return 0.0

    overlap_ratio = overlap / len(u)
    boost = max_artist_boost * overlap_ratio
    return min(boost, max_artist_boost)


def infer_user_language_pref(user_tags: Sequence[str]) -> str:
    """Infer language preference from tags: 'greek'|'english'|'both'."""
    s = {t.lower() for t in user_tags or []}
    has_gr = "lang_greek" in s
    has_en = "lang_english" in s
    if has_gr and has_en:
        return "both"
    if has_en:
        return "english"
    if has_gr:
        return "greek"
    return "both"


def compute_language_match(user_lang_pref: str, event_language: str) -> float:
    """
    Return language match score:
      - 1.0 = good match
      - 0.2 = weak match
    """
    el = (event_language or "").strip().lower()
    ul = (user_lang_pref or "").strip().lower()

    if ul == "both":
        return 1.0
    if ul == "english":
        return 1.0 if el in ("english", "both") else 0.2
    if ul == "greek":
        return 1.0 if el in ("greek", "both") else 0.2
    return 1.0


def in_date_window(event_date: Any, date_from: Any = None, date_to: Any = None, today: Optional[date] = None) -> bool:
    """Check if event is not in past and inside optional [date_from, date_to]."""
    d = _to_date(event_date)
    if not d:
        return False

    if today is None:
        today = date.today()

    if d < today:
        return False

    f = _to_date(date_from)
    if f and d < f:
        return False

    t = _to_date(date_to)
    if t and d > t:
        return False

    return True


def matched_tags_and_artists(
    user_tags: Sequence[str],
    user_artists: Sequence[str],
    ev_tags: Sequence[str],
    ev_artists: Sequence[str],
) -> Tuple[List[str], List[str]]:
    """Return exact overlaps used for explanations."""
    ut = {x.lower() for x in user_tags or []}
    ua = {x.lower() for x in user_artists or []}
    m_tags = [t for t in ev_tags if t.lower() in ut]
    m_art = [a for a in ev_artists if a.lower() in ua]
    return m_tags, m_art


def score_event(
    user_tags,
    user_city,
    user_artists,
    event,
    mode: str,
    w_cbf: float,
    w_context: float,
    max_artist_boost: float,
    w_language: float,
) -> Dict:
    """
    Score a single event.

    A/B mode:
      - baseline: score = CBF only
      - hybrid: w_cbf*CBF + w_context*Context + ArtistBoost + LanguageTerm
    """
    ev_tags = normalize_list(event.get_tags())
    ev_artists = normalize_list(event.get_artists())

    u_tags = normalize_list(user_tags)
    u_artists = normalize_list(user_artists)

    m_tags, m_artists = matched_tags_and_artists(u_tags, u_artists, ev_tags, ev_artists)

    cbf = jaccard_similarity(u_tags, ev_tags)
    city_score = compute_city_score(event.city, user_city)
    context = compute_context_score(event.city, user_city)

    user_lang_pref = infer_user_language_pref(u_tags)
    lang_match = compute_language_match(user_lang_pref, event.language)

    if mode == "baseline":
        artist_boost = 0.0
        w_context_eff = 0.0
        w_language_eff = 0.0
        score = cbf
    else:
        artist_boost = compute_artist_boost(u_artists, ev_artists, max_artist_boost)
        w_context_eff = w_context
        w_language_eff = w_language

        # language term uses (lang_match - 0.2) -> [0..0.8] controlled influence
        score = (
            w_cbf * cbf
            + w_context_eff * context
            + artist_boost
            + (w_language_eff * (lang_match - 0.2))
        )

    score = max(0.0, min(1.0, score))

    explanation_parts = []
    if m_tags:
        explanation_parts.append(f"Matched tags: {', '.join(m_tags)}")
    if m_artists:
        explanation_parts.append(f"Matched artists: {', '.join(m_artists)}")
    explanation_parts.append(f"City proximity: {round(city_score, 2)}")
    explanation_parts.append(f"Language match: {round(lang_match, 2)} ({user_lang_pref} preference)")

    return {
        "id": event.id,
        "title": event.title,
        "city": event.city,
        "date": event.date.isoformat(),
        "language": event.language,
        "tags": ev_tags,
        "artists": ev_artists,
        "score": round(score, 3),
        "why": {
            "matched_tags": m_tags,
            "matched_artists": m_artists,
            "city_score": round(city_score, 3),
            "language_match": round(lang_match, 3),
            "user_language_pref": user_lang_pref,
        },
        "breakdown": {
            "mode": mode,
            "cbf": round(cbf, 3),
            "context": round(context, 3),
            "artist_boost": round(artist_boost, 3),
            "language_term": round((w_language_eff * (lang_match - 0.2)), 3),
            "weights": {
                "w_cbf": w_cbf,
                "w_context": w_context_eff,
                "max_artist_boost": max_artist_boost,
                "w_language": w_language_eff,
            },
        },
        "explanation": " · ".join(explanation_parts),
    }
