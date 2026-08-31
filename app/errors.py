from fastapi import HTTPException
from google.genai.errors import APIError as GeminiAPIError
from postgrest.exceptions import APIError as SupabaseAPIError
from requests import RequestException


def handle_external_error(error: Exception) -> None:
    if isinstance(error, RequestException):
        raise HTTPException(
            status_code=503,
            detail="External League data service is temporarily unavailable."
        )

    if isinstance(error, SupabaseAPIError):
        raise HTTPException(
            status_code=503,
            detail="Database service is temporarily unavailable."
        )

    if isinstance(error, GeminiAPIError):
        error_text = str(error)

        daily_limit_reached = (
            getattr(error, "status_code", None) == 429
            and (
                "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in error_text
                or "generate_content_free_tier_requests" in error_text
            )
        )

        if daily_limit_reached:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "DAILY_LIMIT_REACHED",
                    "message": (
                        "WaveGuide has reached its daily AI request limit. "
                        "Please try again tomorrow."
                    )
                }
            )

        raise HTTPException(
            status_code=503,
            detail="AI service is temporarily unavailable."
        )

    raise HTTPException(
        status_code=500,
        detail="An unexpected server error occurred."
    )