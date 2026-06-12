from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response_type: str
    message: str | None = None
    captured_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    follow_up_question: str | None = None
    city: str | None = None
    itinerary: list[dict[str, Any]] = Field(default_factory=list)
    cost_summary: dict[str, Any] = Field(default_factory=dict)
    budget_message: str | None = None
    saving_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    transport_info: dict[str, Any] = Field(default_factory=dict)
    enrichment: dict[str, Any] = Field(default_factory=dict)
    tool_trace: list[str] = Field(default_factory=list)
    log: dict[str, Any] = Field(default_factory=dict)
    response_language: str | None = None
    data_source: str | None = None
    data_confidence: str | None = None


class ResetResponse(BaseModel):
    session_id: str
    status: str
