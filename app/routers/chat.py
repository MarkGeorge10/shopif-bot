"""
Chat sessions router.
POST   /chat/sessions              — create session (subscription required)
GET    /chat/sessions              — list sessions
GET    /chat/sessions/{id}         — get session with messages
POST   /chat/sessions/{id}/messages — append message
DELETE /chat/sessions/{id}         — delete session
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, require_active_subscription
from app.models.user import User
from app.models.chat_session import ChatSession
from app.schemas.chat import (
    CreateSessionRequest,
    ChatSessionOut,
    ChatSessionDetailOut,
    MessageRequest,
)

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/sessions", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    body: CreateSessionRequest,
    current_user: Annotated[User, Depends(require_active_subscription)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new chat session. Requires an active or trialing subscription."""
    session = ChatSession(
        user_id=current_user.id,
        shop_domain=body.shop_domain,
        title=body.title or "New Chat",
        messages=[],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """List all chat sessions for the current user, newest first."""
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailOut)
def get_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a specific chat session including all messages."""
    session = _get_owned_session(session_id, current_user.id, db)
    return session


@router.post("/sessions/{session_id}/messages", response_model=ChatSessionDetailOut)
def append_message(
    session_id: str,
    body: MessageRequest,
    current_user: Annotated[User, Depends(require_active_subscription)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Append a message to a chat session.
    Subscription gate ensures only active/trialing users can add messages.
    """
    session = _get_owned_session(session_id, current_user.id, db)

    new_message = {
        "role": body.role,
        "content": body.content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # SQLAlchemy won't detect in-place list mutation — assign a new list
    session.messages = [*session.messages, new_message]

    # Auto-title: use first user message if no title was set
    if session.title == "New Chat" and body.role == "user":
        session.title = body.content[:80]

    db.commit()
    db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a chat session."""
    session = _get_owned_session(session_id, current_user.id, db)
    db.delete(session)
    db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_owned_session(session_id: str, user_id: str, db: Session) -> ChatSession:
    """Fetch a session and verify ownership. Raises 404 if not found."""
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return session
