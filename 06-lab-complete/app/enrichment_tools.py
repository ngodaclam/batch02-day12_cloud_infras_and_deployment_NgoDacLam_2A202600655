from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
from dotenv import dotenv_values, load_dotenv


BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR.parent / ".env"


def _load_env() -> dict[str, str | None]:
    load_dotenv(ENV_PATH)
    values = dotenv_values(ENV_PATH)
    return {
        "tavily_api_key": os.getenv("TAVILY_API_KEY") or values.get("TAVILY_API_KEY"),
    }


def _tavily_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    api_key = _load_env().get("tavily_api_key")
    if not api_key:
        return []
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": False,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("results", [])
    except Exception:
        return []


def get_weather_suggestion(city_or_area: str, travel_date: str | None = None) -> dict[str, Any]:
    try:
        response = requests.get(
            f"https://wttr.in/{quote_plus(city_or_area)}",
            params={"format": "j1", "lang": "vi"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current_condition", [{}])[0]
        temp = current.get("temp_C")
        description = ", ".join(item.get("value", "") for item in current.get("weatherDesc", []))
        humidity = current.get("humidity")
        rain = current.get("precipMM")
        summary = f"{city_or_area}: khoảng {temp}°C, {description.lower() or 'chưa rõ mô tả'}, độ ẩm {humidity}%, mưa {rain}mm."
        return {
            "available": True,
            "summary": summary,
            "suggestion": "Nên kiểm tra lại thời tiết sát giờ đi; ưu tiên mang áo mưa/áo khoác nhẹ nếu lịch trình có nhiều điểm ngoài trời.",
            "source": f"https://wttr.in/{quote_plus(city_or_area)}",
            "travel_date": travel_date,
        }
    except Exception:
        results = _tavily_search(f"thời tiết {city_or_area} {travel_date or ''}", max_results=3)
        if not results:
            return {
                "available": False,
                "summary": "Chưa lấy được dữ liệu thời tiết.",
                "suggestion": "Bạn nên kiểm tra app thời tiết trước khi chốt lịch trình ngoài trời.",
                "source": None,
                "travel_date": travel_date,
            }
        return {
            "available": True,
            "summary": results[0].get("content") or results[0].get("title"),
            "suggestion": "Dữ liệu thời tiết lấy từ web search, nên kiểm tra lại trước khi đi.",
            "source": results[0].get("url"),
            "travel_date": travel_date,
        }


def build_map_suggestions(city_or_area: str, starting_location: str | None, itinerary: list[dict[str, Any]]) -> dict[str, Any]:
    place_names = [place.get("name", "") for place in itinerary if place.get("name")]
    waypoints = [starting_location or city_or_area] + place_names
    query = " to ".join(item for item in waypoints if item)
    return {
        "summary": "Mở bản đồ để kiểm tra khoảng cách thực tế, thời gian di chuyển và thứ tự điểm đi trước khi xuất phát.",
        "google_maps_url": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query),
        "place_links": [
            {
                "name": name,
                "url": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name} {city_or_area}"),
            }
            for name in place_names[:10]
        ],
    }


def get_review_summary(city_or_area: str, itinerary: list[dict[str, Any]]) -> dict[str, Any]:
    top_places = [place.get("name", "") for place in itinerary[:3] if place.get("name")]
    query = f"review trải nghiệm du lịch {' '.join(top_places)} {city_or_area}"
    results = _tavily_search(query, max_results=5)
    if not results:
        return {
            "available": False,
            "summary": "Chưa tổng hợp được review từ web.",
            "highlights": [],
            "source_urls": [],
        }

    highlights = []
    source_urls = []
    for item in results[:5]:
        content = item.get("content") or item.get("title") or ""
        if content:
            highlights.append(content[:260])
        if item.get("url"):
            source_urls.append(item["url"])

    return {
        "available": True,
        "summary": "Tổng hợp nhanh từ các kết quả/review công khai trên web. Nội dung chỉ dùng để tham khảo trước khi chốt lịch trình.",
        "highlights": highlights[:3],
        "source_urls": source_urls[:5],
    }


def enrich_trip_context(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("response_type") == "missing_required_input":
        return {}

    captured = result.get("captured_fields", {})
    city = result.get("city") or captured.get("city_or_area")
    if not city:
        return {}

    itinerary = result.get("itinerary", [])
    return {
        "weather": get_weather_suggestion(city, captured.get("travel_date")),
        "map": build_map_suggestions(city, captured.get("starting_location"), itinerary),
        "reviews": get_review_summary(city, itinerary),
    }
