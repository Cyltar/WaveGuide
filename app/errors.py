from fastapi import HTTPException
from google.genai.errors import APIError as GeminiAPIError
from postgrest.exceptions import APIError as SupabaseAPIError
from requests import RequestException


def handle_external_error(error: Exception) -> None:
    """
    Translate external service errors into HTTP errors.
    """
    if isinstance(error, RequestException):
        status = error.response.status_code if error.response is not None else None

        if status == 429:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "RIOT_RATE_LIMITED",
                    "message": ("Riot's data service is temporarily " "rate-limited. Please try again shortly."),
                },
            )
        if status in {401, 403}:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "RIOT_API_UNAVAILABLE",
                    "message": ("Riot's data service is temporarily " "unavailable. Please try again later."),
                },
            )
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail={"code": "LEAGUE_DATA_NOT_FOUND", "message": ("The requested League data could not be found.")},
            )
        raise HTTPException(
            status_code=503,
            detail={"code": "LEAGUE_DATA_UNAVAILABLE", "message": ("External League data is temporarily unavailable.")},
        )
    if isinstance(error, SupabaseAPIError):
        raise HTTPException(
            status_code=503,
            detail={"code": "DATABASE_UNAVAILABLE", "message": ("Database service is temporarily unavailable.")},
        )
    if isinstance(error, GeminiAPIError):
        error_text = str(error)
        daily_limit_reached = getattr(error, "status_code", None) == 429 and (
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in error_text
            or "generate_content_free_tier_requests" in error_text
        )

        if daily_limit_reached:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "DAILY_LIMIT_REACHED",
                    "message": ("WaveGuide has reached its daily AI request limit. " "Please try again tomorrow."),
                },
            )
        raise HTTPException(
            status_code=503, detail={"code": "AI_UNAVAILABLE", "message": ("AI service is temporarily unavailable.")}
        )
    raise HTTPException(
        status_code=500, detail={"code": "UNEXPECTED_ERROR", "message": ("An unexpected server error occurred.")}
    )
