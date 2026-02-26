"""
Chat API endpoints — routes all AI logic through the orchestrator.

POST /api/chat/send              — send message → orchestrator → response
GET  /api/chat/sessions          — list sessions for current user
GET  /api/chat/sessions/{id}     — get session with full history
DELETE /api/chat/sessions/{id}   — delete a session
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from prisma.models import User

from app.api.deps import get_current_active_user
from app.core.database import prisma
from app.services.ai.orchestrator import process_chat_message

logger = logging.getLogger("api.chat")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatSendRequest(BaseModel):
    message: str
    session_id: str | None = None
    store_id: str | None = None
    current_page: str | None = None


class ToolCallOut(BaseModel):
    name: str
    args: dict = {}
    result: dict = {}


class ChatSendResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCallOut] = []
    structured_actions: dict = {}


class ChatSessionOut(BaseModel):
    id: str
    title: str | None = None
    store_id: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatSessionDetailOut(ChatSessionOut):
    messages: list[dict] = []


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/send", response_model=ChatSendResponse)
async def send_chat_message(
    body: ChatSendRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    Send a message to the AI concierge.
    Routes through the orchestrator → Gemini → tool calls → response.
    Requires an active subscription or trial.
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    result = await process_chat_message(
        user_id=current_user.id,
        session_id=body.session_id,
        message=body.message.strip(),
        store_id=body.store_id,
        current_page=body.current_page,
    )

    return ChatSendResponse(
        session_id=result["session_id"],
        reply=result["reply"],
        tool_calls=[ToolCallOut(**tc) for tc in result.get("tool_calls", [])],
        structured_actions=result.get("structured_actions", {}),
    )


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    current_user: User = Depends(get_current_active_user),
):
    """List all chat sessions for the current user, newest first."""
    sessions = await prisma.chatsession.find_many(
        where={"userId": current_user.id},
        order={"updatedAt": "desc"},
    )
    return [
        ChatSessionOut(
            id=s.id,
            title=s.title,
            store_id=s.store_id,
            created_at=s.createdAt,
            updated_at=s.updatedAt,
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailOut)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get a specific chat session including all messages."""
    session = await prisma.chatsession.find_first(
        where={"id": session_id, "userId": current_user.id}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = session.messages if isinstance(session.messages, list) else json.loads(session.messages or "[]")

    return ChatSessionDetailOut(
        id=session.id,
        title=session.title,
        store_id=session.store_id,
        created_at=session.createdAt,
        updated_at=session.updatedAt,
        messages=messages,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a chat session."""
    session = await prisma.chatsession.find_first(
        where={"id": session_id, "userId": current_user.id}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    await prisma.chatsession.delete(where={"id": session.id})
