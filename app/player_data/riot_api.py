import os
from urllib.parse import quote

import requests


RIOT_API_KEY = os.environ.get("RIOT_API_KEY")

REQUEST_TIMEOUT_SECONDS = 30


class RiotRateLimitError(requests.RequestException):
    """
    Raised when Riot returns HTTP 429.

    retry_after contains Riot's Retry-After value when supplied.
    """

    def __init__(self, retry_after: int | None = None):
        """
        Initialize the rate-limit error with the reported retry delay.
        """
        self.retry_after = retry_after

        if retry_after is None:
            message = "Riot API rate limit reached."
        else:
            message = "Riot API rate limit reached. " f"Retry after {retry_after} seconds."
        super().__init__(message)


def request_headers() -> dict:
    """
    Build Riot authentication headers from the environment.
    """
    key = RIOT_API_KEY or os.environ.get("RIOT_API_KEY")

    if not key:
        raise ValueError("Set RIOT_API_KEY before making Riot requests.")
    return {"X-Riot-Token": key}


def riot_get(url: str, *, params: dict | None = None) -> requests.Response:
    """
    Perform a Riot GET request.
    """
    # HTTP 429 is converted into RiotRateLimitError so the analysis
    # service can immediately stop rather than treating the failure
    # as a missing individual match.

    response = requests.get(url, headers=request_headers(), params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After")
        retry_after = None

        if retry_after_header is not None:
            try:
                retry_after = int(retry_after_header)
            except ValueError:
                pass
        raise RiotRateLimitError(retry_after=retry_after)
    response.raise_for_status()

    return response


def get_account_by_riot_id(game_name: str, tag_line: str, routing_region: str = "americas") -> dict:
    """
    Resolve a Riot ID through Riot Account-V1.
    """
    encoded_game_name = quote(game_name, safe="")
    encoded_tag_line = quote(tag_line, safe="")
    url = (
        f"https://{routing_region}.api.riotgames.com"
        f"/riot/account/v1/accounts/by-riot-id/"
        f"{encoded_game_name}/{encoded_tag_line}"
    )
    response = riot_get(url)

    return response.json()


def get_recent_match_ids(puuid: str, routing_region: str = "americas", count: int = 20, start: int = 0) -> list[str]:
    """
    Fetch a page of recent match IDs from Riot Match-V5.
    """
    if not 1 <= count <= 100:
        raise ValueError("count must be between 1 and 100.")
    if start < 0:
        raise ValueError("start must be nonnegative.")
    encoded_puuid = quote(puuid, safe="")
    url = f"https://{routing_region}.api.riotgames.com" f"/lol/match/v5/matches/by-puuid/" f"{encoded_puuid}/ids"
    params = {"start": start, "count": count}
    response = riot_get(url, params=params)

    return response.json()


def get_match(match_id: str, routing_region: str = "americas") -> dict:
    """
    Fetch one match summary from Riot Match-V5.
    """
    encoded_match_id = quote(match_id, safe="")
    url = f"https://{routing_region}.api.riotgames.com" f"/lol/match/v5/matches/" f"{encoded_match_id}"
    response = riot_get(url)

    return response.json()


def get_match_timeline(match_id: str, routing_region: str = "americas") -> dict:
    """
    Fetch one match timeline from Riot Match-V5.
    """
    encoded_match_id = quote(match_id, safe="")
    url = f"https://{routing_region}.api.riotgames.com" f"/lol/match/v5/matches/" f"{encoded_match_id}/timeline"
    response = riot_get(url)

    return response.json()


if __name__ == "__main__":
    account = get_account_by_riot_id(game_name="Cessereendya", tag_line="7944")

    print("Account:")
    print(account["gameName"], "#", account["tagLine"])

    puuid = account["puuid"]
    match_ids = get_recent_match_ids(puuid=puuid, count=3)

    print("\nRecent matches:")
    print(match_ids)

    if match_ids:
        match = get_match(match_ids[0])
        timeline = get_match_timeline(match_ids[0])

        print("\nLatest match ID:")
        print(match_ids[0])

        print("\nMatch keys:")
        print(match.keys())

        print("\nTimeline keys:")
        print(timeline.keys())
