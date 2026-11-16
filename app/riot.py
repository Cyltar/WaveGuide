from functools import lru_cache
import requests

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"


@lru_cache(maxsize=1)
def get_latest_version() -> str:
    """
    Fetch the latest Data Dragon version.
    """
    response = requests.get(VERSIONS_URL, timeout=(5, 15))
    response.raise_for_status()

    versions = response.json()

    return versions[0]


def fetch_champion(champion_name: str) -> dict:
    """
    Fetch champion data from Riot Data Dragon.
    """
    champion_name = champion_name.replace(" ", "").replace("'", "")
    response = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{get_latest_version()}/data/en_US/champion/{champion_name}.json", timeout=(5, 15))
    response.raise_for_status()

    data = response.json()
    return data["data"][champion_name]
