from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import time
import os
from app.auth import AuthenticatedUser, get_current_user
from app.gemini import ask_gemini
from app.database import *
from app.stats import get_role_rankings
from app.supabase_client import create_user_client
from app.query_parser import parse_query
from app.errors import handle_external_error
from app.champions import CHAMPIONS
from app.knowledge.knowledge_loader import load_relevant_knowledge


app = FastAPI(title="WaveGuide", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", os.environ.get("FRONTEND_URL", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# Pydantic Models

class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str


# API Endpoints

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, auth: AuthenticatedUser = Depends(get_current_user)):
    try:
        user_id = auth.user_id
        check_daily_ai_request_limit(user_id)
        user_client = create_user_client(auth.access_token)
        session_id = request.session_id

        if session_id is not None:
            if not user_owns_session(user_client, session_id):
                raise HTTPException(status_code=404, detail="Conversation not found.")

            history = get_chat_history(user_client, session_id)
        else:
            history = []

        context = parse_query(message=request.message, recent_history=history)
        season_knowledge = load_relevant_knowledge(context.knowledge_topics)

        player_data = None
        enemy_data = None
        player_stats = None
        matchup_stats = None
        requested_stats = {}
        role_rankings = None

        if context.requested_champions and context.role is not None:
            for champion in context.requested_champions:
                requested_stats[champion] = get_stats(champion, context.role)

        if context.ranking_metric is not None and context.role is not None:
            ranking_count = context.ranking_count or 5
            role_rankings = get_role_rankings(context.role, context.ranking_metric, ranking_count)

        if context.player_champion is not None:
            player_data = get_champion(context.player_champion)

        if context.enemy_champion is not None:
            enemy_data = get_champion(context.enemy_champion)

        if context.player_champion is not None and context.role is not None:
            player_stats = get_stats(context.player_champion, context.role)
            matchup_stats = get_specific_matchup(player_stats, context.enemy_champion)

        start_time = time.perf_counter()

        answer = ask_gemini(
            user_message=request.message,
            season_knowledge=season_knowledge,
            player_data=player_data,
            enemy_data=enemy_data,
            player_stats=player_stats,
            matchup_stats=matchup_stats,
            requested_stats=requested_stats,
            role_rankings=role_rankings,
            history=history,
            role=context.role,
            query_type=context.query_type
        )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        record_successful_ai_request(user_id)

        if session_id is None:
            session_id = create_chat_session(client=user_client, user_id=user_id, title=request.message[:50])

        save_chat_message(client=user_client, session_id=session_id, role="user", content=request.message)

        used_context = {
            "player_champion": context.player_champion,
            "enemy_champion": context.enemy_champion,
            "requested_champions": context.requested_champions,
            "role": context.role,
            "query_type": context.query_type,
            "matchup_stats": matchup_stats,
            "knowledge_topics": context.knowledge_topics,
            "role_rankings": role_rankings
        }

        save_chat_message(
            client=user_client,
            session_id=session_id,
            role="assistant",
            content=answer,
            used_context=used_context,
            latency_ms=latency_ms
        )

        return ChatResponse(answer=answer, session_id=session_id)

    except HTTPException:
        raise

    except Exception as error:
        handle_external_error(error)


@app.get("/champions")
def get_champions():
    return {"champions": CHAMPIONS}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, auth: AuthenticatedUser = Depends(get_current_user)):
    user_client = create_user_client(auth.access_token)

    if not user_owns_session(user_client, session_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")

    messages = get_session_messages(user_client, session_id)

    return {"messages": messages}


@app.get("/sessions")
def get_sessions(auth: AuthenticatedUser = Depends(get_current_user)):
    user_client = create_user_client(auth.access_token)

    return {"sessions": get_user_sessions(user_client)}
