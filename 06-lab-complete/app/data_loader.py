from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATA_PATH = Path(__file__).parent / "Data" / "Data_10provinces.json"


@dataclass
class CityData:
    metadata: dict[str, Any]
    budget_planning_rules: dict[str, Any]
    transport_options: list[dict[str, Any]]
    places: list[dict[str, Any]]


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    lowered = value.lower().strip()
    lowered = lowered.replace("đ", "d").replace("Đ", "d")
    lowered = unicodedata.normalize("NFD", lowered)
    lowered = "".join(char for char in lowered if unicodedata.category(char) != "Mn")
    replacements = {
        "tp.": "thanh pho ",
        "tp ": "thanh pho ",
        "hcm": "ho chi minh",
        "sai gon": "ho chi minh",
        "saigon": "ho chi minh",
    }
    for old, new in replacements.items():
        lowered = lowered.replace(old, new)
    return " ".join(lowered.split())


def load_all_city_data(data_path: Path = DATA_PATH) -> list[CityData]:
    with data_path.open("r", encoding="utf-8") as file:
        raw_data = json.load(file)

    return [
        CityData(
            metadata=item.get("metadata", {}),
            budget_planning_rules=item.get("budget_planning_rules", {}),
            transport_options=item.get("transport_options", []),
            places=item.get("places", []),
        )
        for item in raw_data
    ]


def list_supported_cities(city_data: list[CityData] | None = None) -> list[str]:
    city_data = city_data or load_all_city_data()
    seen: set[str] = set()
    cities: list[str] = []
    for item in city_data:
        city = item.metadata.get("city", "")
        key = normalize_text(city)
        if city and key not in seen:
            cities.append(city)
            seen.add(key)
    return cities


def find_city_data(city_or_area: str, city_data: list[CityData] | None = None) -> CityData | None:
    city_data = city_data or load_all_city_data()
    query = normalize_text(city_or_area)
    if not query:
        return None

    for item in city_data:
        city = normalize_text(item.metadata.get("city"))
        if city and (city in query or query in city):
            return item

    for item in city_data:
        for place in item.places:
            searchable = " ".join(
                [
                    str(place.get("name", "")),
                    str(place.get("area", "")),
                    str(item.metadata.get("city", "")),
                ]
            )
            if query in normalize_text(searchable):
                return item
    return None


def search_places(
    city: CityData,
    query_places: list[str] | None = None,
    preferences: list[str] | None = None,
    limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    query_places = query_places or []
    preferences = preferences or []
    matched_places: list[dict[str, Any]] = []
    unmatched_places: list[str] = []

    for query in query_places:
        normalized_query = normalize_text(query)
        match = next(
            (
                place
                for place in city.places
                if normalized_query
                and (
                    normalized_query in normalize_text(place.get("name"))
                    or normalized_query in normalize_text(place.get("area"))
                )
            ),
            None,
        )
        if match:
            if match not in matched_places:
                item = dict(match)
                item["required"] = True
                matched_places.append(item)
        else:
            unmatched_places.append(query)

    suggested_places = suggest_places(city, preferences=preferences, exclude=matched_places, limit=limit)
    return {
        "matched_places": matched_places,
        "suggested_places": suggested_places,
        "unmatched_places": unmatched_places,
    }


def suggest_places(
    city: CityData,
    preferences: list[str] | None = None,
    exclude: list[dict[str, Any]] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    preferences = [normalize_text(pref) for pref in (preferences or [])]
    excluded_ids = {place.get("id") for place in (exclude or [])}

    def score(place: dict[str, Any]) -> tuple[int, int, str]:
        tags = " ".join(str(tag) for tag in place.get("tags", []))
        searchable = normalize_text(f"{place.get('name', '')} {place.get('type', '')} {tags}")
        preference_score = sum(1 for pref in preferences if pref and pref in searchable)
        budget_score = 2 if place.get("is_good_for_budget_travelers") else 0
        free_score = 2 if int(place.get("average_cost_per_person") or 0) == 0 else 0
        return (preference_score + budget_score + free_score, -int(place.get("average_cost_per_person") or 0), place.get("name", ""))

    candidates = [place for place in city.places if place.get("id") not in excluded_ids]
    ranked = sorted(candidates, key=score, reverse=True)
    return [dict(place) for place in ranked[:limit]]
