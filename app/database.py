from datetime import datetime, timezone
from fastapi import HTTPException
from supabase import Client

from app.riot import VERSION, fetch_champion
from app.stats import get_champion_stats
from app.supabase_client import supabase


STATS_CACHE_TTL_HOURS = 0
DAILY_AI_REQUEST_LIMIT = 20


def get_cached_champion(champion_name: str) -> dict | None:
    response = supabase.table("champions").select("*").eq("name", champion_name).execute()

    if len(response.data) == 0:
        return None

    return response.data[0]


def save_champion(champion_data: dict) -> None:
    data = {
        "name": champion_data["name"],
        "role_tags": champion_data["tags"],
        "riot_version": VERSION,
        "raw_data": champion_data
    }

    supabase.table("champions").upsert(data, on_conflict="name").execute()


def get_champion(champion_name: str) -> dict:
    cached = get_cached_champion(champion_name)

    if cached is not None and cached["riot_version"] == VERSION:
        return cached["raw_data"]

    champion_data = fetch_champion(champion_name)
    save_champion(champion_data)

    return champion_data


def get_champion_id(champion_name: str) -> int:
    response = supabase.table("champions").select("id, name").execute()
    normalized_target = normalize_name(champion_name)

    for row in response.data:
        if normalize_name(row["name"]) == normalized_target:
            return row["id"]

    raise ValueError(f"Champion not found in database: {champion_name}")


def get_current_patch() -> str:
    parts = VERSION.split(".")

    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"

    return VERSION


def get_cached_champion_stats(champion_id: int, role: str, patch: str) -> dict | None:
    response = (
        supabase.table("champion_stats").select("*").eq("champion_id", champion_id)
        .eq("role", role).eq("patch", patch).execute()
    )

    if len(response.data) == 0:
        return None

    return response.data[0]


def is_stats_cache_fresh(cached: dict) -> bool:
    updated_at = cached.get("updated_at")

    if updated_at is None:
        return False

    updated_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - updated_time

    return age.total_seconds() < STATS_CACHE_TTL_HOURS * 3600


def save_champion_stats(champion_id: int, stats: dict) -> None:
    data = {
        "champion_id": champion_id,
        "role": stats["role"],
        "patch": stats["patch"],
        "win_rate": stats["win_rate"],
        "pick_rate": stats["pick_rate"],
        "ban_rate": stats["ban_rate"],
        "games": stats["games"],
        "skill_order": stats["skill_order"],
        "matchups": stats["matchups"],
        "source": stats["source"],
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    supabase.table("champion_stats").upsert(data, on_conflict="champion_id,role,patch").execute()


def get_stats(champion: str, role: str) -> dict:
    get_champion(champion)

    champion_id = get_champion_id(champion)
    patch = get_current_patch()

    cached = get_cached_champion_stats(champion_id, role, patch)

    if cached is not None and is_stats_cache_fresh(cached):
        return cached

    stats = get_champion_stats(champion, role)

    save_champion_stats(champion_id, stats)

    return stats


def get_specific_matchup(stats: dict | None, enemy_champion: str | None) -> dict | None:
    if stats is None or enemy_champion is None:
        return None

    return stats.get("matchups", {}).get(enemy_champion)


def get_daily_ai_request_count(user_id: str) -> int:
    response = supabase.rpc("get_daily_ai_request_count", {"p_user_id": user_id}).execute()

    return response.data


def check_daily_ai_request_limit(user_id: str) -> None:
    if get_daily_ai_request_count(user_id) >= DAILY_AI_REQUEST_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "DAILY_LIMIT_REACHED",
                "message": "LoLGPT has reached its daily AI request limit. Please try again tomorrow."
            }
        )


def record_successful_ai_request(user_id: str) -> None:
    supabase.rpc("increment_daily_ai_request_count", {"p_user_id": user_id}).execute()


def create_chat_session(client: Client, user_id: str, title: str) -> str:
    response = client.table("chat_sessions").insert({"user_id": user_id, "title": title}).execute()

    return response.data[0]["id"]


def save_chat_message(client: Client, session_id: str, role: str, content: str, used_context: dict | None = None, latency_ms: int | None = None) -> None:
    data = {
        "session_id": session_id,
        "role": role,
        "content": content,
        "used_context": used_context,
        "latency_ms": latency_ms
    }

    client.table("chat_messages").insert(data).execute()


def get_chat_history(client: Client, session_id: str, limit: int = 10) -> list[dict]:
    response = client.table("chat_messages").select("role, content").eq("session_id", session_id).order("created_at", desc=True).limit(limit).execute()

    return list(reversed(response.data))


def get_session_messages(client: Client, session_id: str) -> list[dict]:
    response = client.table("chat_messages").select("id, role, content, used_context, latency_ms, created_at").eq("session_id", session_id).order("created_at").execute()

    return response.data


def normalize_name(name: str) -> str:
    return name.lower().replace(" ", "").replace("'", "").replace(".", "").replace("-", "")


def user_owns_session(client: Client, session_id: str) -> bool:
    response = client.table("chat_sessions").select("id").eq("id", session_id).execute()

    return bool(response.data)


def get_user_sessions(client: Client) -> list[dict]:
    response = client.table("chat_sessions").select("id, title, created_at").order("created_at", desc=True).execute()

    return response.data
