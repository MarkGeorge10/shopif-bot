"""Pydantic schemas for chat session endpoints."""
from datetime import datetime
from pydantic import BaseModel


class MessageRequest(BaseModel):
    role: str   # "user" or "model"
    content: str


class CreateSessionRequest(BaseModel):
    shop_domain: str | None = None
    title: str | None = None


class ChatSessionOut(BaseModel):
    id: str
    shop_domain: str | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionDetailOut(ChatSessionOut):
    messages: list[dict]
