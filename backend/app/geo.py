import math

# Navi Mumbai area centroids (lat, lng)
AREAS: dict[str, tuple[float, float]] = {
    "Nerul": (19.0330, 73.0297),
    "Vashi": (19.0771, 72.9986),
    "Belapur": (19.0236, 73.0396),
    "Kharghar": (19.0473, 73.0699),
    "Sanpada": (19.0640, 73.0110),
    "Airoli": (19.1590, 72.9986),
    "Seawoods": (19.0150, 73.0190),
}

# Generous service-area bounding box
BBOX = {"lat": (18.80, 19.40), "lng": (72.80, 73.30)}

_AREA_LOOKUP = {name.lower(): name for name in AREAS}


def canonical_area(name: str | None) -> str | None:
    if not name:
        return None
    key = str(name).strip().lower()
    return _AREA_LOOKUP.get(key, str(name).strip().title())


def area_centroid(name: str | None) -> tuple[float, float] | None:
    canon = canonical_area(name)
    return AREAS.get(canon) if canon else None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
