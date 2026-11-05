"""
Fetch real geographic data and routing geometries for Hanoi metropolitan area.
Downloads POIs and sample real route corridors from OpenStreetMap / OSRM.
"""

import json
import logging
import ssl
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Curated ground-truth landmarks across Hanoi (Hoan Kiem, Ba Dinh, Cau Giay, Tay Ho, Hai Ba Trung, Dong Da, Ha Dong, Long Bien, Noi Bai)
HANOI_LANDMARKS = [
    {
        "name": "Ho Guom (Turtle Tower)",
        "lat": 21.0285,
        "lon": 105.8542,
        "category": "landmark",
        "district": "Hoan Kiem",
    },
    {"name": "Hanoi Opera House", "lat": 21.0245, "lon": 105.8576, "category": "culture", "district": "Hoan Kiem"},
    {"name": "St. Joseph Cathedral", "lat": 21.0307, "lon": 105.8495, "category": "landmark", "district": "Hoan Kiem"},
    {"name": "Dong Xuan Market", "lat": 21.0381, "lon": 105.8497, "category": "market", "district": "Hoan Kiem"},
    {
        "name": "Temple of Literature (Van Mieu)",
        "lat": 21.0293,
        "lon": 105.8361,
        "category": "culture",
        "district": "Dong Da",
    },
    {
        "name": "Hanoi Railway Station (Ga Ha Noi)",
        "lat": 21.0244,
        "lon": 105.8412,
        "category": "transport",
        "district": "Dong Da",
    },
    {"name": "Vincom Center Ba Trieu", "lat": 21.0116, "lon": 105.8498, "category": "mall", "district": "Hai Ba Trung"},
    {"name": "Times City Mega Mall", "lat": 20.9953, "lon": 105.8687, "category": "mall", "district": "Hai Ba Trung"},
    {"name": "Thong Nhat Park", "lat": 21.0152, "lon": 105.8445, "category": "park", "district": "Hai Ba Trung"},
    {"name": "Bach Mai Hospital", "lat": 21.0028, "lon": 105.8415, "category": "hospital", "district": "Dong Da"},
    {
        "name": "Hanoi Medical University",
        "lat": 21.0034,
        "lon": 105.8317,
        "category": "university",
        "district": "Dong Da",
    },
    {
        "name": "Vietnam National University (Cau Giay)",
        "lat": 21.0378,
        "lon": 105.7828,
        "category": "university",
        "district": "Cau Giay",
    },
    {
        "name": "Keangnam Hanoi Landmark Tower",
        "lat": 21.0167,
        "lon": 105.7839,
        "category": "business",
        "district": "Cau Giay",
    },
    {
        "name": "National Convention Center",
        "lat": 21.0062,
        "lon": 105.7885,
        "category": "convention",
        "district": "Nam Tu Liem",
    },
    {
        "name": "My Dinh National Stadium",
        "lat": 21.0205,
        "lon": 105.7640,
        "category": "sports",
        "district": "Nam Tu Liem",
    },
    {
        "name": "Vincom Center Metropolis (Lieu Giai)",
        "lat": 21.0318,
        "lon": 105.8142,
        "category": "mall",
        "district": "Ba Dinh",
    },
    {"name": "Lotte Center Hanoi", "lat": 21.0326, "lon": 105.8124, "category": "business", "district": "Ba Dinh"},
    {
        "name": "West Lake (Ho Tay - Tran Quoc Pagoda)",
        "lat": 21.0483,
        "lon": 105.8364,
        "category": "landmark",
        "district": "Tay Ho",
    },
    {"name": "Aeon Mall Long Bien", "lat": 21.0261, "lon": 105.9004, "category": "mall", "district": "Long Bien"},
    {"name": "Aeon Mall Ha Dong", "lat": 20.9818, "lon": 105.7538, "category": "mall", "district": "Ha Dong"},
    {
        "name": "Noi Bai International Airport (T1)",
        "lat": 21.2212,
        "lon": 105.8072,
        "category": "airport",
        "district": "Soc Son",
    },
    {
        "name": "Noi Bai International Airport (T2)",
        "lat": 21.2185,
        "lon": 105.7944,
        "category": "airport",
        "district": "Soc Son",
    },
    {"name": "Ho Chi Minh Mausoleum", "lat": 21.0368, "lon": 105.8346, "category": "landmark", "district": "Ba Dinh"},
    {"name": "Royal City Megamall", "lat": 21.0029, "lon": 105.8159, "category": "mall", "district": "Thanh Xuan"},
    {
        "name": "Vincom Mega Mall Smart City",
        "lat": 20.9998,
        "lon": 105.7428,
        "category": "mall",
        "district": "Nam Tu Liem",
    },
    {"name": "Vincom Mega Mall Ocean Park", "lat": 20.9898, "lon": 105.9528, "category": "mall", "district": "Gia Lam"},
    {"name": "Hanoi Museum", "lat": 21.0084, "lon": 105.7877, "category": "culture", "district": "Nam Tu Liem"},
    {
        "name": "Nhat Tan Bridge (South End)",
        "lat": 21.0850,
        "lon": 105.8185,
        "category": "bridge",
        "district": "Tay Ho",
    },
    {
        "name": "Vinh Tuy Bridge (West End)",
        "lat": 21.0055,
        "lon": 105.8752,
        "category": "bridge",
        "district": "Hai Ba Trung",
    },
    {"name": "Chuong Duong Bridge", "lat": 21.0372, "lon": 105.8596, "category": "bridge", "district": "Hoan Kiem"},
]


def fetch_osrm_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> dict | None:
    """Fetch real driving route from public OSRM."""
    url = f"https://router.project-osrm.org/route/v1/driving/{start_lon:.5f},{start_lat:.5f};{end_lon:.5f},{end_lat:.5f}?overview=full&geometries=geojson"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "P063-GIS-Data-Fetcher/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") == "Ok" and data.get("routes"):
                return data["routes"][0]
    except Exception as e:
        logger.warning(f"OSRM route fetch failed ({start_lon},{start_lat} -> {end_lon},{end_lat}): {e}")
    return None


def main():
    out_dir = Path("data/real")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save landmarks
    landmarks_file = out_dir / "hanoi_landmarks.json"
    with open(landmarks_file, "w", encoding="utf-8") as f:
        json.dump(HANOI_LANDMARKS, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(HANOI_LANDMARKS)} real Hanoi landmarks to {landmarks_file}")

    # 2. Fetch sample real corridor routes
    sample_pairs = [
        (0, 12),  # Ho Guom -> Keangnam Landmark (Hoan Kiem -> Cau Giay)
        (0, 20),  # Ho Guom -> Noi Bai Airport (Downtown -> Airport)
        (4, 16),  # Van Mieu -> Lotte Center
        (6, 17),  # Vincom Ba Trieu -> West Lake
        (13, 23),  # Convention Center -> Royal City
        (11, 18),  # VNU -> Aeon Mall Long Bien
    ]

    routes_data = []
    for origin_idx, dest_idx in sample_pairs:
        p1 = HANOI_LANDMARKS[origin_idx]
        p2 = HANOI_LANDMARKS[dest_idx]
        logger.info(f"Fetching real route corridor: '{p1['name']}' -> '{p2['name']}'")
        route = fetch_osrm_route(p1["lon"], p1["lat"], p2["lon"], p2["lat"])
        if route:
            routes_data.append(
                {
                    "origin": p1,
                    "destination": p2,
                    "distance_m": route["distance"],
                    "duration_s": route["duration"],
                    "geometry": route["geometry"],
                }
            )

    routes_file = out_dir / "hanoi_routes.json"
    with open(routes_file, "w", encoding="utf-8") as f:
        json.dump(routes_data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(routes_data)} real route corridors to {routes_file}")


if __name__ == "__main__":
    main()
