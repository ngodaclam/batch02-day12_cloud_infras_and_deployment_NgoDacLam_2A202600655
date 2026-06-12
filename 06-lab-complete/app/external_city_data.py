from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values, load_dotenv
from openai import OpenAI

from data_loader import CityData, normalize_text


BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR.parent / ".env"
CACHE_PATH = BASE_DIR / "Data" / "web_city_cache.json"


def _load_env() -> dict[str, str | None]:
    load_dotenv(ENV_PATH)
    values = dotenv_values(ENV_PATH)
    return {
        "tavily_api_key": os.getenv("TAVILY_API_KEY") or values.get("TAVILY_API_KEY"),
        "llm_api_key": os.getenv("9_ROUTER_API_KEY") or values.get("9_ROUTER_API_KEY"),
        "llm_base_url": os.getenv("9ROUTER_BASE_URL") or values.get("9ROUTER_BASE_URL"),
        "llm_model": os.getenv("9ROUTER_MODEL") or values.get("9ROUTER_MODEL"),
    }


def _read_cache() -> list[dict[str, Any]]:
    if not CACHE_PATH.exists():
        return []
    with CACHE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _write_cache(records: list[dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)


def _record_to_city_data(record: dict[str, Any]) -> CityData:
    return CityData(
        metadata=record.get("metadata", {}),
        budget_planning_rules=record.get("budget_planning_rules", {}),
        transport_options=record.get("transport_options", []),
        places=record.get("places", []),
    )


def _ascii_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFD", value.lower().replace("đ", "d").replace("Đ", "d"))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _is_clean_place_name(name: str, city_or_area: str) -> bool:
    text = _ascii_text(name)
    city = _ascii_text(city_or_area)
    banned_terms = [
        "instagram",
        "facebook",
        "youtube",
        "tuyen dung",
        "viec lam",
        "singapore",
        "trung quoc",
        "nhat ban",
        "han quoc",
        "update tour",
        "so luong co han",
        "combo",
        "khach san",
        "food tour",
        "gia ve",
        "bang gia",
    ]
    generic_terms = [
        "nhung dia diem du lich",
        "top 20",
        "top 15",
        "top 10",
        "top 5",
        "top cac dia diem",
        "top dia diem",
        "dia diem du lich",
        "dia diem tham quan",
        "cac diem du lich",
        "cac diem tham quan",
        "kinh nghiem du lich",
        "cam nang du lich",
        "tour du lich",
        "review cac dia diem",
        "review moi",
        "blog",
        "48h kham pha",
    ]
    if any(term in text for term in banned_terms):
        return False
    if any(term in text for term in generic_terms):
        return False
    return bool(city and city in text) or len(text.split()) <= 8


def _is_relevant_result(item: dict[str, Any], city_or_area: str) -> bool:
    city = _ascii_text(city_or_area)
    combined = _ascii_text(" ".join([item.get("title", ""), item.get("content", ""), item.get("url", "")]))
    banned_terms = [
        "instagram",
        "facebook",
        "youtube",
        "tuyen dung",
        "viec lam",
        "singapore",
        "trung quoc",
        "nhat ban",
        "han quoc",
        "update tour",
    ]
    if any(term in combined for term in banned_terms):
        return False
    return bool(city and city in combined)


def _record_is_usable(record: dict[str, Any]) -> bool:
    city = record.get("metadata", {}).get("city", "")
    places = record.get("places", [])
    clean_count = sum(1 for place in places if _is_clean_place_name(place.get("name", ""), city))
    return clean_count >= 3


def get_cached_external_city(city_or_area: str) -> CityData | None:
    query = normalize_text(city_or_area)
    for record in _read_cache():
        city = normalize_text(record.get("metadata", {}).get("city"))
        if city and (city == query or city in query or query in city):
            if not _record_is_usable(record):
                continue
            return _record_to_city_data(record)
    return None


def _save_external_city(record: dict[str, Any]) -> None:
    records = _read_cache()
    city_key = normalize_text(record.get("metadata", {}).get("city"))
    records = [
        item
        for item in records
        if normalize_text(item.get("metadata", {}).get("city")) != city_key
    ]
    records.append(record)
    _write_cache(records)


def _tavily_search(city_or_area: str) -> dict[str, Any] | None:
    env = _load_env()
    api_key = env.get("tavily_api_key")
    if not api_key:
        return None

    queries = [
        f"địa điểm tham quan nổi tiếng ở {city_or_area} giá vé",
        f"quán ăn ngon giá rẻ ở {city_or_area} review",
        f"quán cafe đẹp ở {city_or_area} review",
    ]
    merged_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    answers: list[str] = []

    for query in queries:
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 6,
                    "include_answer": True,
                    "include_raw_content": False,
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("answer"):
                answers.append(payload["answer"])
            for item in payload.get("results", []):
                url = item.get("url")
                if url and url not in seen_urls:
                    merged_results.append(item)
                    seen_urls.add(url)
        except Exception:
            continue

    if not merged_results:
        return None
    return {"answer": "\n".join(answers), "results": merged_results[:14]}


def _llm_extract_city_data(city_or_area: str, search_payload: dict[str, Any]) -> dict[str, Any] | None:
    env = _load_env()
    api_key = env.get("llm_api_key")
    base_url = env.get("llm_base_url")
    model = env.get("llm_model")
    if not api_key or not base_url or not model:
        return None

    sources = []
    for item in search_payload.get("results", [])[:8]:
        sources.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
            }
        )

    prompt = f"""
You convert web search snippets into safe mock travel planning data.

City/area: {city_or_area}

Rules:
- Use only information supported by the snippets and source URLs.
- If a price is not clearly available, use a conservative estimated price and mark cost_confidence as "low".
- Return Vietnamese names.
- Do not create hotels or booking flows.
- Build enough places for a one-day demo: attractions, breakfast/lunch/dinner/cafe if possible.
- Use types only from: tham_quan, an_sang, an_trua, an_toi, cafe.
- Confidence must be:
  high: at least 5 useful places and 4 distinct source URLs
  medium: at least 4 useful places and 2 distinct source URLs
  low: otherwise

Return only JSON:
{{
  "city": "string",
  "confidence": "low|medium|high",
  "confidence_note": "string",
  "source_urls": ["string"],
  "places": [
    {{
      "name": "string",
      "type": "tham_quan|an_sang|an_trua|an_toi|cafe",
      "area": "string",
      "average_cost_per_person": integer,
      "cost_confidence": "low|medium|high",
      "estimated_duration_minutes": integer,
      "recommended_time_slot": "HH:MM-HH:MM",
      "tags": ["string"],
      "is_good_for_budget_travelers": boolean,
      "saving_tips": ["string"],
      "source_urls": ["string"]
    }}
  ]
}}

Search snippets:
{json.dumps(sources, ensure_ascii=False)}
""".strip()

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=10, max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a careful extraction tool. Return strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        return _extract_json(content)
    except Exception:
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None


def _build_record(extracted: dict[str, Any]) -> dict[str, Any]:
    city = extracted.get("city") or ""
    source_urls = extracted.get("source_urls", [])
    confidence = extracted.get("confidence", "low")

    places = []
    for index, place in enumerate(extracted.get("places", []), start=1):
        name = place.get("name", "")
        if not _is_clean_place_name(name, city):
            continue
        places.append(
            {
                "id": f"web_{normalize_text(city).replace(' ', '_')}_{index:03d}",
                "name": name,
                "type": place.get("type", "tham_quan"),
                "area": place.get("area", city),
                "average_cost_per_person": int(place.get("average_cost_per_person") or 0),
                "cost_confidence": place.get("cost_confidence", "low"),
                "estimated_duration_minutes": int(place.get("estimated_duration_minutes") or 60),
                "recommended_time_slot": place.get("recommended_time_slot", "Linh hoạt"),
                "tags": place.get("tags", []),
                "is_good_for_budget_travelers": bool(place.get("is_good_for_budget_travelers", True)),
                "saving_tips": place.get("saving_tips", []),
                "source_urls": place.get("source_urls", source_urls),
            }
        )

    return {
        "metadata": {
            "project_name": "AI Travel Budget Planner",
            "city": city,
            "currency": "VND",
            "version": "web-cache-1.0",
            "description": "Dữ liệu lấy từ web fallback, cần hiển thị confidence và nguồn.",
            "data_source": "web_cache",
            "confidence": confidence,
            "confidence_note": extracted.get("confidence_note", ""),
            "source_urls": source_urls,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "budget_planning_rules": {
            "budget_status": {
                "within_budget": "Tổng chi phí <= ngân sách người dùng",
                "over_budget": "Tổng chi phí > ngân sách người dùng",
            },
            "required_place_policy": "Các địa điểm có required=true phải được giữ lại trong lịch trình, kể cả khi làm vượt ngân sách.",
            "suggestion_policy": "Dữ liệu web-cache phải hiển thị confidence; giá low-confidence chỉ là ước lượng.",
            "cost_formula": "total_cost = sum(place_cost_per_person * number_of_people) + transport_cost_total",
        },
        "transport_options": [
            {
                "id": f"web_transport_walk_{normalize_text(city).replace(' ', '_')}",
                "name": "Đi bộ / gom điểm gần nhau",
                "estimated_cost_per_trip": 0,
                "best_for": "Các lịch trình trung tâm hoặc các điểm gần nhau.",
                "saving_tip": "Vì đây là dữ liệu web fallback, hãy ưu tiên gom các điểm gần nhau và kiểm tra lại quãng đường trước khi đi.",
            },
            {
                "id": f"web_transport_grab_{normalize_text(city).replace(' ', '_')}",
                "name": "Taxi công nghệ / xe ôm công nghệ",
                "estimated_cost_per_trip": 50000,
                "best_for": "Di chuyển linh hoạt khi chưa có dữ liệu tuyến đường chính xác.",
                "saving_tip": "So sánh giá trên app trước khi đặt; chi phí này chỉ là ước lượng demo.",
            },
        ],
        "places": places,
    }


def _heuristic_extract_city_data(city_or_area: str, search_payload: dict[str, Any]) -> dict[str, Any] | None:
    results = search_payload.get("results", [])
    if not results:
        return None

    filtered_results = [item for item in results if _is_relevant_result(item, city_or_area)]
    source_urls = [item.get("url") for item in filtered_results if item.get("url")][:6]
    if len(source_urls) < 2:
        return None

    type_cycle = ["tham_quan", "an_sang", "an_trua", "cafe", "tham_quan", "an_toi"]
    default_costs = {
        "tham_quan": 50000,
        "an_sang": 40000,
        "an_trua": 80000,
        "cafe": 45000,
        "an_toi": 80000,
    }
    time_slots = {
        "an_sang": "07:30-08:15",
        "tham_quan": "09:00-10:30",
        "an_trua": "12:00-13:00",
        "cafe": "15:00-15:45",
        "an_toi": "18:30-19:30",
    }

    places = []
    used_names: set[str] = set()
    for index, item in enumerate(filtered_results[:8]):
        place_type = type_cycle[index % len(type_cycle)]
        raw_title = item.get("title") or f"Gợi ý tại {city_or_area}"
        name = raw_title.split("|")[0].split("-")[0].strip()
        if len(name) > 80:
            name = name[:77].strip() + "..."
        normalized_name = normalize_text(name)
        if not normalized_name or normalized_name in used_names:
            continue
        if not _is_clean_place_name(name, city_or_area):
            continue
        used_names.add(normalized_name)
        places.append(
            {
                "name": name,
                "type": place_type,
                "area": city_or_area,
                "average_cost_per_person": default_costs[place_type],
                "cost_confidence": "low",
                "estimated_duration_minutes": 60,
                "recommended_time_slot": time_slots[place_type],
                "tags": ["web_fallback", "ước lượng"],
                "is_good_for_budget_travelers": default_costs[place_type] <= 50000,
                "saving_tips": [
                    "Dữ liệu này được suy luận từ web search, hãy kiểm tra lại giá/giờ mở cửa trước khi đi."
                ],
                "source_urls": [item.get("url")] if item.get("url") else source_urls[:2],
            }
        )

    if len(places) < 3:
        return None

    return {
        "city": city_or_area,
        "confidence": "low",
        "confidence_note": "LLM chuẩn hóa không phản hồi, nên agent dùng heuristic từ kết quả Tavily. Giá chỉ là ước lượng demo.",
        "source_urls": source_urls,
        "places": places,
    }


def fetch_external_city_data(city_or_area: str) -> CityData | None:
    cached = get_cached_external_city(city_or_area)
    if cached:
        return cached

    search_payload = _tavily_search(city_or_area)
    if not search_payload:
        return None

    extracted = _llm_extract_city_data(city_or_area, search_payload)
    if not extracted or not extracted.get("places"):
        extracted = _heuristic_extract_city_data(city_or_area, search_payload)
    if not extracted or not extracted.get("places"):
        return None

    record = _build_record(extracted)
    if not _record_is_usable(record):
        return None
    _save_external_city(record)
    return _record_to_city_data(record)


def fetch_external_cafe_recommendations(city_or_area: str, limit: int = 4) -> list[dict[str, Any]]:
    env = _load_env()
    api_key = env.get("tavily_api_key")
    llm_api_key = env.get("llm_api_key")
    base_url = env.get("llm_base_url")
    model = env.get("llm_model")
    if not api_key:
        return []

    ascii_city = _ascii_text(city_or_area).title()
    queries = [
        f"quán cafe ngon đẹp ở {city_or_area} review",
        f"{ascii_city} coffee shop cafe review Vietnam",
        f"{ascii_city} specialty coffee cafe review",
    ]
    merged_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in queries:
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 6,
                    "include_answer": True,
                    "include_raw_content": False,
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue
        for item in payload.get("results", []):
            url = item.get("url")
            if url and url not in seen_urls:
                merged_results.append(item)
                seen_urls.add(url)

    results = [item for item in merged_results if _is_relevant_result(item, city_or_area)]
    if not results:
        return []

    sources = [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "content": item.get("content"),
        }
        for item in results[:6]
    ]
    prompt = f"""
Extract concrete cafe recommendations from these web snippets.

City/area: {city_or_area}

Rules:
- Return only cafes or drink/dessert shops clearly supported by snippets.
- Do not return article titles, tour titles, ticket price pages, hotel pages, Instagram/Facebook/Youtube pages, or generic "top cafe" titles.
- If you cannot identify concrete cafe names, return an empty places array.
- Use Vietnamese names when available.
- average_cost_per_person can be conservative estimate in VND if snippets do not show a price.

Return only JSON:
{{
  "places": [
    {{
      "name": "string",
      "area": "string",
      "average_cost_per_person": integer,
      "recommended_time_slot": "string",
      "source_urls": ["string"]
    }}
  ]
}}

Search snippets:
{json.dumps(sources, ensure_ascii=False)}
""".strip()

    extracted = None
    if llm_api_key and base_url and model:
        try:
            client = OpenAI(api_key=llm_api_key, base_url=base_url, timeout=10, max_retries=0)
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a strict extraction tool. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )
            extracted = _extract_json(completion.choices[0].message.content or "")
        except Exception:
            extracted = None

    cafes: list[dict[str, Any]] = []
    for index, item in enumerate((extracted or {}).get("places", []), start=1):
        name = str(item.get("name", "")).strip()
        if not name or not _is_clean_place_name(name, city_or_area):
            continue
        searchable = _ascii_text(" ".join([name, str(item.get("area", ""))]))
        if any(term in searchable for term in ["gia ve", "tour", "du lich", "khach san", "instagram", "facebook"]):
            continue
        cafes.append(
            {
                "id": f"web_cafe_{normalize_text(city_or_area).replace(' ', '_')}_{index:03d}",
                "name": name,
                "type": "cafe",
                "area": item.get("area") or city_or_area,
                "average_cost_per_person": int(item.get("average_cost_per_person") or 45000),
                "cost_confidence": "low",
                "estimated_duration_minutes": 45,
                "recommended_time_slot": item.get("recommended_time_slot") or "Linh hoạt",
                "tags": ["web_fallback", "cafe"],
                "is_good_for_budget_travelers": True,
                "saving_tips": ["Kiểm tra lại giờ mở cửa và mức giá trước khi đi."],
                "source_urls": item.get("source_urls") or [source.get("url") for source in sources if source.get("url")][:2],
            }
        )
        if len(cafes) >= limit:
            break
    if not cafes:
        cafes = _heuristic_cafe_recommendations(city_or_area, results, limit)
    return cafes


def _heuristic_cafe_recommendations(city_or_area: str, results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    bad_terms = [
        "top ",
        "best cafe",
        "best cafes",
        "guide",
        "review",
        "instagram",
        "facebook",
        "tiktok",
        "youtube",
        "blog",
        "booking",
        "booking.com",
        "restaurant review",
        "quán cafe đẹp",
        "quan cafe dep",
        "những quán",
        "nhung quan",
    ]
    patterns = [
        r"([A-ZÀ-Ỹ][A-Za-zÀ-ỹ0-9'&.\s-]{1,45}(?:Coffee|Café|Cafe|Cà Phê|Ca Phe))",
        r"\b((?:Cong|Cộng|Nối|Noi|Ibasho|P Coffee|Roots|The Cups|Sơn Trà|Son Tra|Boulevard|XLIII)[A-Za-zÀ-ỹ0-9'&.\s-]{0,35})",
    ]
    candidates: list[tuple[str, str | None]] = []
    for result in results:
        url = result.get("url")
        title = str(result.get("title", ""))
        content = str(result.get("content", ""))
        title_candidate = re.split(r"\s*[-,|]\s*(?:Da Nang|Đà Nẵng|Danang|Restaurants|Tripadvisor)", title, maxsplit=1)[0]
        title_key = _ascii_text(title_candidate)
        combined_key = _ascii_text(f"{title} {content}")
        if (
            3 <= len(title_candidate) <= 55
            and any(term in combined_key for term in ["coffee", "cafe", "ca phe"])
            and not any(term in title_key for term in bad_terms)
        ):
            candidates.append((title_candidate.title() if title_candidate.isupper() else title_candidate, url))
        for text in [title, content.replace("·", "\n").replace("•", "\n")]:
            for pattern in patterns:
                for match in re.findall(pattern, text):
                    name = " ".join(str(match).strip(" -–:,.#").split())
                    name = re.split(r"\s*[-,|]\s*(?:Da Nang|Đà Nẵng|Danang|Restaurants|Tripadvisor)", name, maxsplit=1)[0]
                    key = _ascii_text(name)
                    if len(name) < 3 or len(name) > 55:
                        continue
                    if len(name.split()) > 6:
                        continue
                    if any(term in key for term in bad_terms):
                        continue
                    if key in {"coffee", "cafe", "ca phe", "quan cafe", "quan ca phe"}:
                        continue
                    if any(term in key for term in [" la mot ", " chuyen phuc vu", "chuyen phuc"]):
                        continue
                    candidates.append((name, url))

    cafes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, (name, url) in enumerate(candidates, start=1):
        key = normalize_text(name)
        if key in seen:
            continue
        seen.add(key)
        cafes.append(
            {
                "id": f"web_cafe_{normalize_text(city_or_area).replace(' ', '_')}_{index:03d}",
                "name": name,
                "type": "cafe",
                "area": city_or_area,
                "average_cost_per_person": 45000,
                "cost_confidence": "low",
                "estimated_duration_minutes": 45,
                "recommended_time_slot": "Linh hoạt",
                "tags": ["web_fallback", "cafe"],
                "is_good_for_budget_travelers": True,
                "saving_tips": ["Kiểm tra lại giờ mở cửa và mức giá trước khi đi."],
                "source_urls": [url] if url else [],
            }
        )
        if len(cafes) >= limit:
            break
    return cafes
