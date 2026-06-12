from __future__ import annotations

import math
import unicodedata
from typing import Any


FOOD_TYPES = {"an_sang", "an_trua", "an_toi", "food", "restaurant"}
CAFE_TYPES = {"cafe", "coffee"}


ROUTE_TRANSPORT_ESTIMATES = [
    {
        "from": ["hoi an", "quang nam"],
        "to": ["da nang"],
        "mode": "Xe shuttle / Grab Car Hội An - Đà Nẵng",
        "estimated_cost_total": 350000,
        "tip": "Tuyến Hội An - Đà Nẵng nên tính riêng chi phí vào/ra thành phố; đi nhóm 3 người dùng Grab Car hoặc shuttle thường hợp lý hơn đi từng chặng lẻ.",
    },
    {
        "from": ["rach gia", "ha tien"],
        "to": ["kien giang", "phu quoc"],
        "mode": "Xe trung chuyển nội tỉnh / taxi bến tàu",
        "estimated_cost_total": 220000,
        "tip": "Nếu đi Phú Quốc cần tính thêm vé tàu/phà riêng; bản demo hiện chỉ ước lượng phần trung chuyển nội tỉnh.",
    },
    {
        "from": ["ho xuan huong", "trung tam da lat", "cho da lat"],
        "to": ["da lat"],
        "mode": "Di chuyển nội thành Đà Lạt",
        "estimated_cost_total": 60000,
        "tip": "Các điểm trung tâm có thể gom để đi bộ, nhưng ra Cầu Đất/Tà Nung nên thuê xe máy hoặc đặt xe công nghệ.",
    },
    {
        "from": ["san bay lien khuong", "lien khuong"],
        "to": ["da lat"],
        "mode": "Xe sân bay Liên Khương - Đà Lạt",
        "estimated_cost_total": 220000,
        "tip": "Từ sân bay vào trung tâm nên tính thêm shuttle/taxi trước khi bắt đầu lịch trình trong thành phố.",
    },
]


def vnd(value: int | float | None) -> str:
    if value is None:
        amount = 0
    elif isinstance(value, float) and math.isnan(value):
        amount = 0
    else:
        amount = int(value or 0)
    return f"{amount:,}".replace(",", ".") + " VND"


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFD", value.lower().replace("đ", "d").replace("Đ", "d"))
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(normalized.split())


def estimate_route_cost(starting_location: str | None, city_name: str | None) -> dict[str, Any] | None:
    start_key = _normalize_text(starting_location)
    city_key = _normalize_text(city_name)
    if not start_key or not city_key:
        return None

    for route in ROUTE_TRANSPORT_ESTIMATES:
        from_match = any(token in start_key for token in route["from"])
        to_match = any(token in city_key for token in route["to"])
        if from_match and to_match:
            return dict(route)
    return None


def estimate_transport_cost(
    transport_options: list[dict[str, Any]],
    number_of_people: int,
    transport_preference: str | None,
    number_of_segments: int,
    starting_location: str | None = None,
    city_name: str | None = None,
) -> dict[str, Any]:
    preference = (transport_preference or "").lower()
    options = transport_options or []
    route_cost = estimate_route_cost(starting_location, city_name)

    if not options:
        return {
            "transport_mode": "Ước lượng di chuyển",
            "estimated_transport_cost": 0,
            "saving_tip": "Chưa có dữ liệu phương tiện trong mock data.",
        }

    def option_cost(option: dict[str, Any]) -> int:
        cost = int(option.get("estimated_cost_per_trip") or 0)
        name = str(option.get("name", "")).lower()
        if "grab" in name or "taxi" in name:
            return cost * max(number_of_segments, 1)
        if "xe máy" in name or "xe may" in _normalize_text(name) or "rental" in name:
            bikes_needed = max((number_of_people + 1) // 2, 1)
            return cost * bikes_needed
        return cost * max(number_of_segments, 1)

    if "đi bộ" in preference or "di bo" in preference or "walk" in preference:
        selected = next((item for item in options if "di bo" in _normalize_text(str(item.get("name", "")))), options[0])
    elif "grab" in preference or "taxi" in preference:
        selected = next((item for item in options if "grab" in str(item.get("name", "")).lower() or "taxi" in str(item.get("name", "")).lower()), options[0])
    elif "xe máy" in preference or "xe may" in preference or "thuê" in preference or "thue" in preference:
        selected = next((item for item in options if "xe may" in _normalize_text(str(item.get("name", "")))), options[0])
    else:
        practical_options = [
            option
            for option in options
            if not ("di bo" in _normalize_text(str(option.get("name", ""))) and number_of_segments > 2)
        ]
        selected = min(practical_options or options, key=option_cost)

    local_cost = option_cost(selected)
    route_total = int(route_cost.get("estimated_cost_total") or 0) if route_cost else 0
    route_legs = []
    if route_cost:
        route_legs.append(
            {
                "name": route_cost["mode"],
                "estimated_cost": route_total,
                "note": route_cost["tip"],
            }
        )
    route_legs.append(
        {
            "name": selected.get("name", "Phương tiện nội thành"),
            "estimated_cost": local_cost,
            "note": selected.get("best_for", ""),
        }
    )

    return {
        "transport_mode": selected.get("name", "Phương tiện đề xuất"),
        "estimated_transport_cost": local_cost + route_total,
        "local_transport_cost": local_cost,
        "route_transport_cost": route_total,
        "route_legs": route_legs,
        "saving_tip": route_cost["tip"] if route_cost else selected.get("saving_tip", ""),
        "best_for": selected.get("best_for", ""),
    }


def calculate_trip_cost(
    itinerary: list[dict[str, Any]],
    number_of_people: int,
    transport_cost: int,
) -> dict[str, Any]:
    food_cost = 0
    cafe_cost = 0
    activity_cost = 0
    rows: list[dict[str, Any]] = []

    for item in itinerary:
        place_type = str(item.get("type", "tham_quan"))
        cost_per_person = int(item.get("average_cost_per_person") or 0)
        total = cost_per_person * number_of_people

        if place_type in FOOD_TYPES:
            category = "Ăn uống"
            food_cost += total
        elif place_type in CAFE_TYPES:
            category = "Cafe"
            cafe_cost += total
        else:
            category = "Đi chơi / tham quan"
            activity_cost += total

        rows.append(
            {
                "Hạng mục": category,
                "Tên": item.get("name", ""),
                "Chi phí/người": cost_per_person,
                "Số người": number_of_people,
                "Tổng chi phí": total,
            }
        )

    rows.append(
        {
            "Hạng mục": "Di chuyển",
            "Tên": "Chi phí di chuyển dự kiến",
            "Chi phí/người": None,
            "Số người": number_of_people,
            "Tổng chi phí": transport_cost,
        }
    )

    total_cost = food_cost + cafe_cost + activity_cost + int(transport_cost or 0)
    return {
        "food_cost": food_cost,
        "cafe_cost": cafe_cost,
        "activity_cost": activity_cost,
        "transport_cost": int(transport_cost or 0),
        "total_cost": total_cost,
        "cost_rows": rows,
    }


def check_budget_status(budget_cap: int, total_cost: int) -> dict[str, Any]:
    remaining = int(budget_cap or 0) - int(total_cost or 0)
    if remaining >= 0:
        ratio = total_cost / budget_cap if budget_cap else 1
        status = "NEAR_LIMIT" if ratio >= 0.85 else "WITHIN_BUDGET"
        return {
            "status": status,
            "remaining_budget": remaining,
            "over_budget_amount": 0,
        }

    return {
        "status": "OVER_BUDGET",
        "remaining_budget": 0,
        "over_budget_amount": abs(remaining),
    }


def generate_saving_suggestions(
    itinerary: list[dict[str, Any]],
    over_budget_amount: int,
    transport_info: dict[str, Any],
    number_of_people: int,
) -> dict[str, Any]:
    suggestions: list[dict[str, Any]] = []

    saving_tip = transport_info.get("saving_tip")
    if saving_tip:
        suggestions.append(
            {
                "type": "transport",
                "title": "Tối ưu chi phí di chuyển",
                "detail": saving_tip,
                "estimated_saving": None,
            }
        )

    for item in itinerary:
        alternative = item.get("cheaper_alternative")
        if not alternative:
            continue
        saving_per_person = int(alternative.get("estimated_saving_per_person") or 0)
        suggestions.append(
            {
                "type": "place_alternative",
                "title": f"Đổi '{item.get('name')}'",
                "detail": f"Cân nhắc '{alternative.get('name')}'. {alternative.get('note', '')}".strip(),
                "estimated_saving": saving_per_person * number_of_people,
            }
        )

    for item in itinerary:
        for tip in item.get("saving_tips", [])[:1]:
            suggestions.append(
                {
                    "type": "saving_tip",
                    "title": f"Mẹo tiết kiệm tại {item.get('name')}",
                    "detail": tip,
                    "estimated_saving": None,
                }
            )

    minimum_budget = None
    if over_budget_amount > 0:
        current_total_from_required = sum(
            int(item.get("average_cost_per_person") or 0) * number_of_people
            for item in itinerary
            if item.get("required")
        )
        if current_total_from_required:
            minimum_budget = current_total_from_required + int(transport_info.get("estimated_transport_cost") or 0)

    return {
        "suggestions": suggestions[:5],
        "minimum_budget_to_keep_required_places": minimum_budget,
    }
