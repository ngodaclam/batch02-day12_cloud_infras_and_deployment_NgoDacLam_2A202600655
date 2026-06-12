from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


LOG_DIR = Path(__file__).parent / "logs"
LOG_PATH = LOG_DIR / "agent_runs.jsonl"


def build_reasoning_summary(result: dict[str, Any]) -> list[str]:
    captured = result.get("captured_fields", {})
    summary: list[str] = []

    if result.get("response_type") == "missing_required_input":
        missing = ", ".join(result.get("missing_fields", []))
        summary.append(f"Thiếu input bắt buộc: {missing}. Agent dừng lập tour và hỏi lại.")
        return summary

    mode = result.get("response_type")
    city = result.get("city") or captured.get("city_or_area")
    status = result.get("cost_summary", {}).get("status")
    data_source = result.get("data_source", "mock_data")

    summary.append(f"Đã xác định khu vực {city}, ngân sách {captured.get('budget_cap')} VND, số người {captured.get('number_of_people')}.")
    summary.append("Không có địa điểm bắt buộc nên dùng inspire mode." if mode == "inspire_mode" else "Có địa điểm/user preference nên lập lịch trình theo yêu cầu.")
    summary.append(f"Dữ liệu sử dụng: {data_source}.")
    summary.append(f"Đã tính tổng chi phí và phân loại trạng thái ngân sách: {status}.")
    if status == "OVER_BUDGET":
        summary.append("Vì vượt ngân sách, agent giữ điểm bắt buộc và sinh gợi ý tiết kiệm.")
    else:
        summary.append("Vì chưa vượt ngân sách, agent gợi ý có thể cải thiện trải nghiệm.")
    return summary


def summarize_output(result: dict[str, Any]) -> dict[str, Any]:
    cost_summary = result.get("cost_summary", {})
    return {
        "response_type": result.get("response_type"),
        "city": result.get("city"),
        "itinerary_count": len(result.get("itinerary", [])),
        "total_cost": cost_summary.get("total_cost"),
        "budget_status": cost_summary.get("status"),
        "missing_fields": result.get("missing_fields", []),
        "data_source": result.get("data_source"),
        "data_confidence": result.get("data_confidence"),
    }


def log_agent_run(user_input: str, result: dict[str, Any]) -> dict[str, Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    record = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_input": user_input,
        "captured_fields": result.get("captured_fields", {}),
        "tool_trace": result.get("tool_trace", []),
        "reasoning_summary": build_reasoning_summary(result),
        "output_summary": summarize_output(result),
    }
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"run_id": run_id, "log_path": str(LOG_PATH)}
