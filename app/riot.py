import requests

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"

def get_latest_version() -> str:
    response = requests.get(VERSIONS_URL)
    response.raise_for_status()

    versions = response.json()

    return versions[0]

VERSION = get_latest_version()
BASE_URL = (
    f"https://ddragon.leagueoflegends.com/cdn/"
    f"{VERSION}/data/en_US/champion")


def fetch_champion(champion_name: str) -> dict:
    """
    Fetch champion data from Riot Data Dragon.
    """
    champion_name = champion_name.replace(" ", "").replace("'", "")

    response = requests.get(f"{BASE_URL}/{champion_name}.json")
    response.raise_for_status()

    data = response.json()
    return data["data"][champion_name]
