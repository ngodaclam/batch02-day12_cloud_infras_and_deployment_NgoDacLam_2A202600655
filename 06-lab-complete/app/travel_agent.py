from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv
from openai import OpenAI

from budget_calculator import (
    calculate_trip_cost,
    check_budget_status,
    estimate_transport_cost,
    generate_saving_suggestions,
    vnd,
)
from data_loader import find_city_data, list_supported_cities, load_all_city_data, normalize_text, search_places
from external_city_data import fetch_external_city_data
from agent_logger import log_agent_run
from enrichment_tools import enrich_trip_context


BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "tools" / "budget_travel_agent_tools_config.json"
ENV_PATH = BASE_DIR.parent / ".env"


FIELD_LABELS = {
    "budget_cap": "ngân sách tổng cho cả nhóm",
    "number_of_people": "số người tham gia",
    "city_or_area": "thành phố/khu vực muốn đi",
    "starting_location": "điểm xuất phát",
}

FIELD_LABELS_EN = {
    "budget_cap": "total budget for the group",
    "number_of_people": "number of travelers",
    "city_or_area": "target city or area",
    "starting_location": "starting location",
}


def detect_response_language(user_text: str) -> str:
    vietnamese_chars = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
    lowered = user_text.lower()
    if any(char in vietnamese_chars for char in lowered):
        return "vi"
    english_markers = [
        "travel",
        "trip",
        "budget",
        "itinerary",
        "from",
        "people",
        "destination",
        "where",
        "what",
        "write",
        "code",
        "hello",
        "help",
        "please",
        "suggest",
        "coffee",
        "shop",
        "shops",
        "restaurant",
    ]
    return "en" if any(marker in lowered for marker in english_markers) else "vi"


def is_out_of_scope_request(user_text: str) -> bool:
    lowered = user_text.lower()
    explicit_non_travel = [
        "viết code",
        "python",
        "javascript",
        "bóng đá",
        "bitcoin",
        "chứng khoán",
        "làm thơ",
        "kể chuyện",
        "dịch bài",
        "homework",
        "write code",
        "stock",
        "crypto",
        "football",
        "poem",
        "translate",
    ]
    if any(term in lowered for term in explicit_non_travel):
        return True

    travel_signals = [
        "đi",
        "từ",
        "tu ",
        "lên",
        "len ",
        "đến",
        "den ",
        "du lịch",
        "tour",
        "lịch trình",
        "ngân sách",
        "xuất phát",
        "địa điểm",
        "tham quan",
        "chơi",
        "có gì",
        "quán",
        "ngon",
        "ăn",
        "cafe",
        "cà phê",
        "check-in",
        "thời tiết",
        "review",
        "bản đồ",
        "travel",
        "trip",
        "itinerary",
        "budget",
        "from",
        "to ",
        "destination",
        "restaurant",
        "coffee",
        "coffee shop",
        "coffee shops",
        "weather",
        "map",
        "nearby",
        "good place",
        "things to do",
    ]
    return not any(signal in lowered for signal in travel_signals)


def localized_message(key: str, language: str, **kwargs: Any) -> str:
    messages = {
        "out_of_scope": {
            "vi": "Mình là trợ lý lập lịch trình du lịch theo ngân sách, nên mình chỉ xử lý các câu hỏi liên quan đến chuyến đi, địa điểm, chi phí, ăn uống, di chuyển, thời tiết hoặc review. Bạn hãy gửi yêu cầu du lịch kèm ngân sách, số người, khu vực và điểm xuất phát nhé.",
            "en": "I am a travel budget planning assistant, so I can only help with trip planning, destinations, costs, food, transport, weather, maps, or reviews. Please send a travel request with budget, number of travelers, destination, and starting location.",
        },
        "missing_required": {
            "vi": "Mình còn thiếu: {labels}. Bạn bổ sung giúp mình để mình tạo tour nhé.",
            "en": "I still need: {labels}. Please provide those details before I create an itinerary.",
        },
        "unsupported_destination": {
            "vi": "Mình chưa có dữ liệu đủ tin cậy cho khu vực '{city}', nên mình sẽ không tự tạo lịch trình để tránh bịa địa điểm hoặc chi phí. Bạn có thể chọn một nơi phổ biến như {cities}.",
            "en": "I do not have reliable enough data for '{city}', so I will not create a made-up itinerary. You can choose one of the supported sample cities: {cities}, or try a more common destination.",
        },
    }
    return messages[key][language].format(**kwargs)


def load_agent_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_llm_client() -> tuple[OpenAI | None, str | None]:
    load_dotenv(ENV_PATH)
    values = dotenv_values(ENV_PATH)

    api_key = os.getenv("9_ROUTER_API_KEY") or values.get("9_ROUTER_API_KEY")
    base_url = os.getenv("9ROUTER_BASE_URL") or values.get("9ROUTER_BASE_URL")
    model = os.getenv("9ROUTER_MODEL") or values.get("9ROUTER_MODEL")

    if not api_key or not base_url or not model:
        return None, None
    return OpenAI(api_key=api_key, base_url=base_url, timeout=5, max_retries=0), model


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def parse_user_request_with_llm(user_text: str, config: dict[str, Any]) -> dict[str, Any] | None:
    client, model = load_llm_client()
    if not client or not model:
        return None

    supported_cities = ", ".join(list_supported_cities())
    prompt = f"""
Extract trip planning fields from the user's Vietnamese request.

Supported cities in mock data: {supported_cities}

Return only valid JSON with this schema:
{{
  "budget_cap": integer or null,
  "number_of_people": integer or null,
  "city_or_area": string or null,
  "starting_location": string or null,
  "desired_places": array of strings,
  "number_of_days": integer or null,
  "travel_date": string or null,
  "travel_preferences": array of strings,
  "transport_preference": string or null,
  "meal_preferences": array of strings
}}

Do not invent missing required fields. If the user says they do not know where to go,
leave desired_places empty but keep city_or_area if present.

User request:
{user_text}
""".strip()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": config.get("system_prompt", "")},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            timeout=8,
        )
        content = response.choices[0].message.content or ""
        return _extract_json_object(content)
    except Exception:
        return None


def _parse_budget(text: str) -> int | None:
    normalized = text.lower()
    patterns = [
        r"(\d+(?:[\.,]\d+)?)\s*(triệu|trieu|m)\b",
        r"(\d+(?:[\.,]\d+)?)\s*(k|nghìn|nghin)\b",
        r"(\d[\d\.,\s]{3,})\s*(đ|vnd|vnđ)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        raw_amount = match.group(1)
        unit = match.group(2) if len(match.groups()) > 1 else ""
        if unit in {"triệu", "trieu", "m", "k", "nghìn", "nghin"}:
            amount = float(raw_amount.replace(",", "."))
        else:
            return _parse_vnd_integer(raw_amount)
        if unit in {"triệu", "trieu", "m"}:
            return int(amount * 1_000_000)
        if unit in {"k", "nghìn", "nghin"}:
            return int(amount * 1_000)
    return None


def _parse_vnd_integer(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).lower().strip()
    if not text:
        return None

    compact = re.sub(r"\s+", "", text)
    compact = compact.replace("vnd", "").replace("vnđ", "").replace("đ", "")

    unit_match = re.fullmatch(r"(\d+(?:[\.,]\d+)?)(triệu|trieu|m|k|nghìn|nghin)", compact)
    if unit_match:
        number = float(unit_match.group(1).replace(",", "."))
        unit = unit_match.group(2)
        return int(number * (1_000_000 if unit in {"triệu", "trieu", "m"} else 1_000))

    digits_only = re.sub(r"[^\d]", "", compact)
    if not digits_only:
        return None
    return int(digits_only)


def _parse_people(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(người|nguoi|bạn|ban|people|persons|travelers|travellers|pax)", text.lower())
    if match:
        return int(match.group(1))
    return None


def _parse_trip_days(text: str) -> int:
    normalized = text.lower()
    match = re.search(r"(\d+)\s*(ngày|ngay|day|days)\b", normalized)
    if match:
        return max(1, min(int(match.group(1)), 14))
    match = re.search(r"(\d+)\s*(đêm|dem|night|nights)\b", normalized)
    if match:
        return max(1, min(int(match.group(1)) + 1, 14))
    return 1


def _clean_city_or_area(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip(" .,")
    if not text:
        return None
    text = re.split(r"\b(?:thích|thich|và thích|va thich|chưa biết|chua biet)\b", text, maxsplit=1)[0]
    text = re.sub(r"\b\d+\s*(ngày|ngay|đêm|dem|hôm|hom)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(1 ngày|mot ngay|một ngày)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\s*(người|nguoi|bạn|ban|people|persons|travelers|travellers|pax)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+(?:[\.,]\d+)?\s*(triệu|trieu|m|k|nghìn|nghin|vnd|vnđ|đ)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:for\s+)?\d+\s*(day|days|night|nights)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bfor one day\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:travel to|go to|visit|to)\s+", "", text, flags=re.IGNORECASE)
    return " ".join(text.strip(" .,").split()) or None


def _coerce_parsed_request(parsed: dict[str, Any]) -> dict[str, Any]:
    parsed["budget_cap"] = _parse_vnd_integer(parsed.get("budget_cap"))
    parsed["city_or_area"] = _clean_city_or_area(parsed.get("city_or_area"))

    people = parsed.get("number_of_people")
    if isinstance(people, str):
        match = re.search(r"\d+", people)
        parsed["number_of_people"] = int(match.group(0)) if match else None
    elif isinstance(people, float):
        parsed["number_of_people"] = int(people)

    days = parsed.get("number_of_days")
    if isinstance(days, str):
        match = re.search(r"\d+", days)
        parsed["number_of_days"] = max(1, min(int(match.group(0)), 14)) if match else 1
    elif isinstance(days, float):
        parsed["number_of_days"] = max(1, min(int(days), 14))
    elif not isinstance(days, int) or days <= 0:
        parsed["number_of_days"] = 1
    else:
        parsed["number_of_days"] = max(1, min(days, 14))

    for field in ["desired_places", "travel_preferences", "meal_preferences"]:
        value = parsed.get(field)
        if value is None:
            parsed[field] = []
        elif isinstance(value, str):
            parsed[field] = [value] if value.strip() else []

    return parsed


def _fallback_parse_user_request(user_text: str) -> dict[str, Any]:
    city_data = load_all_city_data()
    lower = user_text.lower()
    starting_location = None
    start_patterns = [
        r"(?:^|\s)(?:từ|tu)\s+([^,.]+?)\s+(?:lên|len|đến|den|tới|toi|ra|vào|vao)\s+[^,.]+",
        r"(?:xuất phát từ|xuat phat tu|bắt đầu từ|bat dau tu|đi từ|di tu)\s+([^,.]+)",
        r"(?:ở|o)\s+([^,.]+)\s+(?:muốn|muon|đi|di)",
        r"(?:starting from|start from|departing from|from)\s+([^,.]+?)(?:\s+(?:to|and|with|for)\s+|[,.]|$)",
    ]
    for pattern in start_patterns:
        match = re.search(pattern, lower)
        if match:
            starting_location = match.group(1).strip()
            break

    target_segment = None
    target_match = re.search(
        r"(?:muốn đi|muon di|đến|den|lên|len|tới|toi|ra|vào|vao|du lịch|du lich|tham quan|travel to|go to|visit|to)\s+([^,.]+)",
        lower,
    )
    if target_match:
        target_segment = _clean_city_or_area(target_match.group(1))
    if not target_segment:
        for pattern in [
            r"(?:ở|o|in)\s+([^?.,]+?)(?:\s+(?:không|khong|nào|nao)|[?.,]|$)",
            r"^\s*([^?.,]+?)\s+(?:có gì|co gi|things to do)",
        ]:
            match = re.search(pattern, lower)
            if match:
                target_segment = _clean_city_or_area(match.group(1))
                break

    city_or_area = None
    supported_cities = list_supported_cities(city_data)
    search_texts = [target_segment] if target_segment else [lower]
    for search_text in search_texts:
        if not search_text:
            continue
        normalized_search_text = normalize_text(search_text)
        for city in supported_cities:
            normalized_city = normalize_text(city)
            if normalized_city and (normalized_city in normalized_search_text or normalized_search_text in normalized_city):
                city_or_area = city
                break
        if city_or_area:
            break

    if not city_or_area and not target_segment:
        normalized_lower = normalize_text(lower)
        for city in supported_cities:
            normalized_city = normalize_text(city)
            if normalized_city and normalized_city in normalized_lower:
                city_or_area = city
                break
    if not city_or_area and target_segment:
        city_or_area = target_segment.strip()

    desired_places: list[str] = []
    for item in city_data:
        for place in item.places:
            name = place.get("name", "")
            compact_name = name.split("&")[0].split("(")[0].strip()
            if compact_name and compact_name.lower() in lower:
                desired_places.append(compact_name)

    no_destination_words = ["chưa biết đi đâu", "chua biet di dau", "gợi ý", "goi y", "inspire"]
    if any(phrase in lower for phrase in no_destination_words):
        desired_places = []

    preferences = []
    for keyword in ["rẻ", "re", "check-in", "ăn uống", "an uong", "văn hóa", "van hoa", "đi bộ", "di bo", "cafe", "quán cafe", "quan cafe"]:
        if keyword in lower:
            preferences.append(keyword)

    transport_preference = None
    for keyword in ["đi bộ", "di bo", "grab", "taxi", "xe máy", "xe may", "thuê xe"]:
        if keyword in lower:
            transport_preference = keyword
            break

    return {
        "budget_cap": _parse_budget(user_text),
        "number_of_people": _parse_people(user_text),
        "city_or_area": city_or_area,
        "_explicit_city_or_area": target_segment,
        "starting_location": starting_location,
        "desired_places": desired_places,
        "number_of_days": _parse_trip_days(user_text),
        "travel_date": None,
        "travel_preferences": preferences,
        "transport_preference": transport_preference,
        "meal_preferences": [],
    }


def parse_user_request(user_text: str, config: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_user_request_with_llm(user_text, config)
    fallback_parsed = _fallback_parse_user_request(user_text)
    if not parsed:
        parsed = fallback_parsed
    else:
        if fallback_parsed.get("_explicit_city_or_area"):
            parsed["city_or_area"] = fallback_parsed["_explicit_city_or_area"]
        if int(fallback_parsed.get("number_of_days") or 1) > 1:
            parsed["number_of_days"] = fallback_parsed["number_of_days"]
        for field, value in fallback_parsed.items():
            if field.startswith("_"):
                continue
            if parsed.get(field) in [None, "", []] and value not in [None, "", []]:
                parsed[field] = value

    defaults = {
        "budget_cap": None,
        "number_of_people": None,
        "city_or_area": None,
        "starting_location": None,
        "desired_places": [],
        "number_of_days": 1,
        "travel_date": None,
        "travel_preferences": [],
        "transport_preference": None,
        "meal_preferences": [],
    }
    defaults.update(parsed)
    defaults.pop("_explicit_city_or_area", None)
    detected_days = _parse_trip_days(user_text)
    if detected_days > 1:
        defaults["number_of_days"] = detected_days
    return _coerce_parsed_request(defaults)


def validate_required_inputs(parsed_request: dict[str, Any]) -> dict[str, Any]:
    missing = [
        field
        for field in FIELD_LABELS
        if parsed_request.get(field) in [None, "", []]
    ]
    if missing:
        return {
            "is_valid": False,
            "missing_fields": missing,
            "mode": "missing_required_input",
        }
    return {
        "is_valid": True,
        "missing_fields": [],
        "mode": "normal" if parsed_request.get("desired_places") else "inspire_mode",
    }


def build_itinerary(
    matched_places: list[dict[str, Any]],
    suggested_places: list[dict[str, Any]],
    mode: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    itinerary = [dict(place) for place in matched_places]

    preferred_order = ["an_sang", "tham_quan", "an_trua", "cafe", "tham_quan", "an_toi"]
    if mode == "inspire_mode":
        pool = suggested_places
    else:
        pool = [place for place in suggested_places if place.get("id") not in {p.get("id") for p in itinerary}]

    for place_type in preferred_order:
        if len(itinerary) >= limit:
            break
        match = next(
            (
                place
                for place in pool
                if place.get("type") == place_type and place.get("id") not in {p.get("id") for p in itinerary}
            ),
            None,
        )
        if match:
            itinerary.append(dict(match))

    for place in pool:
        if len(itinerary) >= limit:
            break
        if place.get("id") not in {p.get("id") for p in itinerary}:
            itinerary.append(dict(place))

    itinerary.sort(key=lambda item: item.get("recommended_time_slot") or "99:99")
    return itinerary


def _dedupe_places(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for place in places:
        key = str(place.get("id") or place.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(place))
    return unique


def _daily_variant(source: dict[str, Any], day: int, place_type: str, variant_index: int = 0) -> dict[str, Any]:
    variants = {
        "an_sang": [
            ("Bữa sáng địa phương gần điểm xuất phát", "Khu trung tâm", 40000, "08:00-08:45"),
            ("Xôi, bánh mì hoặc món sáng bình dân", "Khu trung tâm", 35000, "08:00-08:40"),
            ("Bún/phở/quán sáng địa phương", "Khu dân cư gần điểm tham quan", 45000, "08:00-08:45"),
            ("Món sáng nhẹ để giữ ngân sách", "Gần điểm xuất phát", 35000, "08:00-08:40"),
        ],
        "an_trua": [
            ("Cơm phần hoặc quán địa phương buổi trưa", "Khu trung tâm", 55000, "11:30-12:20"),
            ("Món đặc sản địa phương mức bình dân", "Gần điểm tham quan", 65000, "11:30-12:30"),
            ("Bún/mì/cơm quán nhỏ", "Khu dân cư", 50000, "11:30-12:20"),
            ("Bữa trưa nâng cấp nhẹ trong ngân sách", "Khu trung tâm", 75000, "11:30-12:30"),
        ],
        "an_toi": [
            ("Ăn tối món địa phương bình dân", "Khu trung tâm", 90000, "18:30-19:45"),
            ("Dạo chợ/đường ăn uống và ăn vặt", "Khu trung tâm", 80000, "18:30-20:00"),
            ("Bữa tối món Việt dễ chia theo nhóm", "Gần điểm lưu trú", 100000, "18:30-20:00"),
            ("Quán tối đông khách địa phương", "Khu dân cư", 85000, "18:30-19:45"),
        ],
        "cafe": [
            ("Cafe view đẹp để nghỉ chân", "Khu trung tâm", 60000, "15:30-16:30"),
            ("Trà/cafe nhẹ sau giờ tham quan", "Gần điểm tham quan", 45000, "15:30-16:15"),
            ("Cafe yên tĩnh cho nhóm nhỏ", "Khu trung tâm", 55000, "15:30-16:30"),
            ("Kem/trà chiều địa phương", "Khu trung tâm", 50000, "15:30-16:15"),
        ],
        "tham_quan": [
            ("Dạo phố và chụp ảnh kiến trúc địa phương", "Khu trung tâm", 0, "09:00-10:30"),
            ("Tham quan hồ/công viên hoặc quảng trường gần trung tâm", "Khu trung tâm", 0, "14:00-15:00"),
            ("Khám phá khu văn hóa địa phương", "Khu văn hóa", 30000, "09:00-10:30"),
            ("Check-in phố đi bộ và không gian công cộng", "Khu trung tâm", 0, "16:00-17:30"),
        ],
    }
    options = variants.get(place_type) or variants["tham_quan"]
    name, area, cost, time_slot = options[variant_index % len(options)]
    item = dict(source)
    item.update(
        {
            "name": name,
            "area": area,
            "average_cost_per_person": cost,
            "recommended_time_slot": time_slot,
            "estimated_duration_minutes": source.get("estimated_duration_minutes") or 60,
            "tags": [*source.get("tags", []), "daily_variant"],
            "is_good_for_budget_travelers": cost <= 70000,
        }
    )
    return item


def _next_place(bucket: list[dict[str, Any]], cursor: int, day: int, place_type: str) -> tuple[dict[str, Any] | None, int]:
    if not bucket:
        return None, cursor
    should_variant = cursor >= len(bucket)
    source = dict(bucket[cursor % len(bucket)])
    if should_variant:
        source = _daily_variant(source, day, place_type, cursor - len(bucket))
    cursor += 1
    source["day"] = day
    source["type"] = source.get("type") or place_type
    if should_variant or day > 1:
        source["id"] = f"{source.get('id') or normalize_text(source.get('name', 'place')).replace(' ', '_')}_day_{day}_{cursor}"
    return source, cursor


def build_multi_day_itinerary(
    matched_places: list[dict[str, Any]],
    suggested_places: list[dict[str, Any]],
    all_places: list[dict[str, Any]],
    mode: str,
    number_of_days: int,
) -> list[dict[str, Any]]:
    if number_of_days <= 1:
        return build_itinerary(matched_places, suggested_places, mode)

    pool = _dedupe_places([*matched_places, *suggested_places, *all_places])
    buckets: dict[str, list[dict[str, Any]]] = {
        "an_sang": [],
        "tham_quan": [],
        "an_trua": [],
        "cafe": [],
        "an_toi": [],
    }
    for place in pool:
        place_type = str(place.get("type", "tham_quan"))
        buckets.setdefault(place_type, []).append(place)

    cursors = {key: 0 for key in buckets}
    itinerary: list[dict[str, Any]] = []
    day_patterns = [
        ["an_sang", "tham_quan", "an_trua", "tham_quan", "cafe", "an_toi"],
        ["an_sang", "tham_quan", "tham_quan", "an_trua", "cafe", "an_toi"],
        ["an_sang", "tham_quan", "an_trua", "cafe", "tham_quan", "an_toi"],
    ]

    required = _dedupe_places(matched_places)
    for index, place in enumerate(required):
        item = dict(place)
        item["day"] = min(index + 1, number_of_days)
        item["required"] = True
        itinerary.append(item)

    for day in range(1, number_of_days + 1):
        existing_types = [str(item.get("type", "tham_quan")) for item in itinerary if item.get("day") == day]
        for place_type in day_patterns[(day - 1) % len(day_patterns)]:
            if place_type in {"an_sang", "an_trua", "an_toi", "cafe"} and place_type in existing_types:
                continue
            place, next_cursor = _next_place(buckets.get(place_type, []), cursors.get(place_type, 0), day, place_type)
            cursors[place_type] = next_cursor
            if not place:
                continue
            itinerary.append(place)
            existing_types.append(place_type)

    itinerary.sort(key=lambda item: (int(item.get("day") or 1), item.get("recommended_time_slot") or "99:99"))
    return itinerary


def optimize_itinerary_for_budget(
    itinerary: list[dict[str, Any]],
    all_places: list[dict[str, Any]],
    number_of_people: int,
    budget_cap: int,
    transport_cost: int,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not itinerary or budget_cap <= 0:
        return itinerary

    current = calculate_trip_cost(itinerary, number_of_people, transport_cost)["total_cost"]
    target_min = int(budget_cap * 0.68)
    target_max = int(budget_cap * 0.9)
    if current >= target_min:
        return itinerary

    selected_ids = {place.get("id") for place in itinerary}
    type_counts: dict[str, int] = {}
    for place in itinerary:
        place_type = str(place.get("type", "tham_quan"))
        type_counts[place_type] = type_counts.get(place_type, 0) + 1

    max_type_counts = {
        "an_sang": 1,
        "an_trua": 1,
        "an_toi": 1,
        "cafe": 1,
        "tham_quan": 5,
    }

    def candidate_score(place: dict[str, Any]) -> tuple[int, int, int, str]:
        place_type = str(place.get("type", "tham_quan"))
        cost = int(place.get("average_cost_per_person") or 0)
        budget_fit = 2 if place.get("is_good_for_budget_travelers") else 0
        paid_experience = 2 if cost > 0 else 0
        type_bonus = 2 if place_type in {"tham_quan", "cafe"} else 1
        return (budget_fit + paid_experience + type_bonus, cost, int(place.get("estimated_duration_minutes") or 0), str(place.get("name", "")))

    candidates = [
        dict(place)
        for place in all_places
        if place.get("id") not in selected_ids and int(place.get("average_cost_per_person") or 0) > 0
    ]
    candidates.sort(key=candidate_score, reverse=True)

    optimized = [dict(place) for place in itinerary]
    total = current
    for place in candidates:
        if len(optimized) >= limit or total >= target_min:
            break
        place_type = str(place.get("type", "tham_quan"))
        if type_counts.get(place_type, 0) >= max_type_counts.get(place_type, 2):
            continue
        added_cost = int(place.get("average_cost_per_person") or 0) * number_of_people
        if total + added_cost > target_max:
            continue
        place["budget_reason"] = "Thêm vào vì ngân sách còn dư nhiều và hoạt động này tăng trải nghiệm mà vẫn nằm trong trần chi phí."
        optimized.append(place)
        selected_ids.add(place.get("id"))
        type_counts[place_type] = type_counts.get(place_type, 0) + 1
        total += added_cost

    if total < target_min:
        for candidate in candidates:
            if candidate.get("id") in selected_ids:
                continue
            candidate_type = str(candidate.get("type", "tham_quan"))
            candidate_cost = int(candidate.get("average_cost_per_person") or 0) * number_of_people
            for index, existing in enumerate(optimized):
                if existing.get("required") or str(existing.get("type", "tham_quan")) != candidate_type:
                    continue
                existing_cost = int(existing.get("average_cost_per_person") or 0) * number_of_people
                new_total = total - existing_cost + candidate_cost
                if existing_cost >= candidate_cost or new_total > target_max:
                    continue
                replacement = dict(candidate)
                replacement["budget_reason"] = "Đổi sang lựa chọn trải nghiệm tốt hơn vì ngân sách còn dư."
                optimized[index] = replacement
                selected_ids.add(candidate.get("id"))
                total = new_total
                break
            if total >= target_min:
                break

    optimized.sort(key=lambda item: item.get("recommended_time_slot") or "99:99")
    return optimized


def trim_itinerary_to_budget(
    itinerary: list[dict[str, Any]],
    number_of_people: int,
    budget_cap: int,
    transport_cost: int,
) -> list[dict[str, Any]]:
    trimmed = [dict(item) for item in itinerary]
    protected_types = {"an_sang", "an_trua", "an_toi"}

    def total_cost(items: list[dict[str, Any]]) -> int:
        return int(calculate_trip_cost(items, number_of_people, transport_cost)["total_cost"])

    while total_cost(trimmed) > budget_cap:
        removable_indexes = [
            index
            for index, item in enumerate(trimmed)
            if not item.get("required")
            and str(item.get("type", "tham_quan")) not in protected_types
            and int(item.get("average_cost_per_person") or 0) > 0
        ]
        if not removable_indexes:
            break
        remove_index = max(
            removable_indexes,
            key=lambda index: int(trimmed[index].get("average_cost_per_person") or 0),
        )
        trimmed.pop(remove_index)

    trimmed.sort(key=lambda item: (int(item.get("day") or 1), item.get("recommended_time_slot") or "99:99"))
    return trimmed


def has_budget_safe_upgrade(
    all_places: list[dict[str, Any]],
    itinerary: list[dict[str, Any]],
    number_of_people: int,
    remaining_budget: int,
) -> bool:
    if remaining_budget <= 0:
        return False
    used_ids = {item.get("id") for item in itinerary}
    used_names = {normalize_text(item.get("name")) for item in itinerary}
    buffer_amount = 50000
    for place in all_places:
        cost = int(place.get("average_cost_per_person") or 0) * number_of_people
        if cost <= 0 or cost > max(remaining_budget - buffer_amount, 0):
            continue
        if place.get("id") in used_ids or normalize_text(place.get("name")) in used_names:
            continue
        return True
    return False


def run_budget_travel_agent(user_text: str) -> dict[str, Any]:
    config = load_agent_config()
    language = detect_response_language(user_text)
    if is_out_of_scope_request(user_text):
        result = {
            "response_type": "out_of_scope",
            "message": localized_message("out_of_scope", language),
            "captured_fields": {},
            "missing_fields": [],
            "itinerary": [],
            "cost_summary": {},
            "budget_message": "",
            "saving_suggestions": [],
            "response_language": language,
            "tool_trace": ["classify_intent", "reject_out_of_scope"],
        }
        result["log"] = log_agent_run(user_text, result)
        return result

    parsed = parse_user_request(user_text, config)
    parsed["response_language"] = language
    validation = validate_required_inputs(parsed)

    if not validation["is_valid"]:
        label_map = FIELD_LABELS if language == "vi" else FIELD_LABELS_EN
        labels = [label_map[field] for field in validation["missing_fields"]]
        result = {
            "response_type": "missing_required_input",
            "captured_fields": parsed,
            "missing_fields": validation["missing_fields"],
            "follow_up_question": localized_message("missing_required", language, labels=", ".join(labels)),
            "itinerary": [],
            "cost_summary": {},
            "budget_message": "",
            "saving_suggestions": [],
            "response_language": language,
            "tool_trace": ["parse_user_request", "validate_required_inputs", "ask_missing_fields"],
        }
        result["log"] = log_agent_run(user_text, result)
        return result

    all_city_data = load_all_city_data()
    city = find_city_data(parsed["city_or_area"], all_city_data)
    used_web_fallback = False
    if not city:
        city = fetch_external_city_data(parsed["city_or_area"])
        used_web_fallback = city is not None
        if not city:
            supported_cities = ", ".join(list_supported_cities(all_city_data))
            result = {
                "response_type": "unsupported_destination",
                "captured_fields": parsed,
                "missing_fields": [],
                "message": localized_message(
                    "unsupported_destination",
                    language,
                    city=parsed.get("city_or_area"),
                    cities=supported_cities,
                ),
                "itinerary": [],
                "cost_summary": {},
                "budget_message": "",
                "saving_suggestions": [],
                "response_language": language,
                "tool_trace": ["parse_user_request", "validate_required_inputs", "search_mock_places", "web_search_costs_failed"],
            }
            result["log"] = log_agent_run(user_text, result)
            return result

    place_result = search_places(
        city,
        query_places=parsed.get("desired_places", []),
        preferences=parsed.get("travel_preferences", []),
        limit=8,
    )
    mode = validation["mode"]
    number_of_days = int(parsed.get("number_of_days") or 1)
    itinerary = build_multi_day_itinerary(
        place_result["matched_places"],
        place_result["suggested_places"],
        city.places,
        mode,
        number_of_days,
    )
    transport_info = estimate_transport_cost(
        city.transport_options,
        int(parsed["number_of_people"]),
        parsed.get("transport_preference"),
        number_of_segments=max(len(itinerary) - 1, 1),
        starting_location=parsed.get("starting_location"),
        city_name=city.metadata.get("city"),
    )
    if number_of_days <= 1:
        itinerary = optimize_itinerary_for_budget(
            itinerary,
            city.places,
            int(parsed["number_of_people"]),
            int(parsed["budget_cap"]),
            int(transport_info["estimated_transport_cost"]),
        )
    else:
        itinerary = trim_itinerary_to_budget(
            itinerary,
            int(parsed["number_of_people"]),
            int(parsed["budget_cap"]),
            int(transport_info["estimated_transport_cost"]),
        )
    transport_info = estimate_transport_cost(
        city.transport_options,
        int(parsed["number_of_people"]),
        parsed.get("transport_preference"),
        number_of_segments=max(len(itinerary) - 1, 1),
        starting_location=parsed.get("starting_location"),
        city_name=city.metadata.get("city"),
    )
    if number_of_days > 1:
        itinerary = trim_itinerary_to_budget(
            itinerary,
            int(parsed["number_of_people"]),
            int(parsed["budget_cap"]),
            int(transport_info["estimated_transport_cost"]),
        )
    cost_summary = calculate_trip_cost(
        itinerary,
        int(parsed["number_of_people"]),
        int(transport_info["estimated_transport_cost"]),
    )
    budget_status = check_budget_status(int(parsed["budget_cap"]), int(cost_summary["total_cost"]))

    saving_result = {"suggestions": [], "minimum_budget_to_keep_required_places": None}
    if budget_status["status"] == "OVER_BUDGET":
        saving_result = generate_saving_suggestions(
            itinerary,
            budget_status["over_budget_amount"],
            transport_info,
            int(parsed["number_of_people"]),
        )

    status_text = {
        "WITHIN_BUDGET": f"Trong ngân sách. Còn dư {vnd(budget_status['remaining_budget'])}.",
        "NEAR_LIMIT": f"Vẫn trong ngân sách nhưng đã gần chạm trần. Còn dư {vnd(budget_status['remaining_budget'])}.",
        "OVER_BUDGET": f"Vượt ngân sách {vnd(budget_status['over_budget_amount'])}. Mình giữ các điểm bắt buộc và đề xuất cách tiết kiệm bên dưới.",
    }[budget_status["status"]]
    can_upgrade = has_budget_safe_upgrade(
        city.places,
        itinerary,
        int(parsed["number_of_people"]),
        int(budget_status["remaining_budget"]),
    )
    if budget_status["status"] != "OVER_BUDGET" and can_upgrade:
        status_text += " Bạn có muốn mình cải thiện lịch trình để trải nghiệm tốt hơn trong phần ngân sách còn lại không?"
    if number_of_days > 1:
        status_text = f"Lịch trình {number_of_days} ngày. " + status_text

    metadata = city.metadata or {}

    result = {
        "response_type": mode if mode == "inspire_mode" else "itinerary_result",
        "captured_fields": parsed,
        "city": city.metadata.get("city"),
        "data_source": metadata.get("data_source", "mock_data"),
        "data_confidence": metadata.get("confidence", "high"),
        "confidence_note": metadata.get("confidence_note", ""),
        "source_urls": metadata.get("source_urls", []),
        "fetched_at": metadata.get("fetched_at"),
        "unmatched_places": place_result["unmatched_places"],
        "itinerary": itinerary,
        "transport_info": transport_info,
        "cost_summary": {**cost_summary, **budget_status},
        "budget_message": status_text,
        "saving_suggestions": saving_result["suggestions"],
        "minimum_budget_to_keep_required_places": saving_result["minimum_budget_to_keep_required_places"],
        "response_language": language,
        "tool_trace": [
            "parse_user_request",
            "validate_required_inputs",
            "search_mock_places" if not used_web_fallback else "web_search_costs",
            "cache_external_city_data" if used_web_fallback else "use_mock_data",
            "estimate_transport_cost",
            "build_itinerary",
            "optimize_itinerary_for_budget",
            "estimate_transport_cost_after_optimization",
            "calculate_trip_cost",
            "check_budget_status",
            "generate_saving_suggestions" if budget_status["status"] == "OVER_BUDGET" else "skip_saving_suggestions",
            "get_weather_suggestion",
            "build_map_suggestions",
            "get_review_summary",
        ],
    }
    result["enrichment"] = enrich_trip_context(result)
    result["log"] = log_agent_run(user_text, result)
    return result
