import re

import requests
from bs4 import BeautifulSoup

from app.champions import CHAMPIONS


BASE_URL = "https://lolalytics.com/lol"

ROLE_MAP = {"Top": "top", "Jungle": "jungle", "Mid": "middle", "ADC": "bottom", "Support": "support"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    )
}


def get_champion_stats(champion: str, role: str) -> dict:
    """
    Fetch and extract champion statistics from LoLalytics.
    """
    lane = get_lane(role)
    champion_slug = normalize_champion_slug(champion)
    build_url = f"{BASE_URL}/{champion_slug}/build/?lane={lane}&tier=emerald_plus"
    counters_url = f"{BASE_URL}/{champion_slug}/counters/?lane={lane}&vslane={lane}&tier=emerald_plus"
    build_soup = get_page(build_url)
    build_text = " ".join(build_soup.stripped_strings)
    counters_soup = get_page(counters_url)
    counters_text = " ".join(counters_soup.stripped_strings)

    return {
        "champion": champion,
        "role": role,
        "patch": extract_patch(build_text),
        "win_rate": extract_percentage(build_text, "Win Rate"),
        "pick_rate": extract_percentage(build_text, "Pick Rate"),
        "ban_rate": extract_percentage(build_text, "Ban Rate"),
        "games": extract_games(build_text),
        "skill_order": extract_skill_order(build_text),
        "matchups": extract_all_matchups(counters_text),
        "source": "lolalytics",
    }


def get_role_rankings(role: str, metric: str, count: int) -> dict:
    """
    Fetch and rank champions for the requested role and metric.
    """
    lane = get_lane(role)
    url = f"{BASE_URL}/tierlist/?lane={lane}&tier=emerald_plus"
    soup = get_page(url)
    text = " ".join(soup.stripped_strings)
    entries = extract_role_ranking_entries(soup)

    if len(entries) == 0:
        raise ValueError("Could not read role-wide statistics from LoLalytics.")
    entries = [entry for entry in entries if entry[metric] is not None]
    entries.sort(key=lambda entry: entry[metric], reverse=True)

    return {
        "role": role,
        "metric": metric,
        "patch": extract_patch(text),
        "entries": entries[:count],
        "source": "lolalytics",
    }


def get_lane(role: str) -> str:
    """
    Map a supported role to its LoLalytics lane name.
    """
    lane = ROLE_MAP.get(role)

    if lane is None:
        raise ValueError(f"Invalid role: {role}")
    return lane


def get_page(url: str) -> BeautifulSoup:
    """
    Fetch an HTML page and parse it with BeautifulSoup.
    """
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


def extract_role_ranking_entries(soup: BeautifulSoup) -> list[dict]:
    """
    Extract champion statistics from tier-list rows.
    """
    entries = []

    for row in soup.find_all("div"):
        cells = row.find_all("div", recursive=False)

        if len(cells) < 10:
            continue
        rank = cells[0].get_text(" ", strip=True)
        champion = normalize_tierlist_champion(cells[2].get_text(" ", strip=True))

        if not rank.isdigit() or champion is None:
            continue
        win_rate = extract_row_number(cells[5].get_text(" ", strip=True))
        pick_rate = extract_row_number(cells[6].get_text(" ", strip=True))
        ban_rate = extract_row_number(cells[7].get_text(" ", strip=True))
        games = extract_games_from_row(cells[9].get_text(" ", strip=True))

        if win_rate is None or pick_rate is None or ban_rate is None:
            continue
        entries.append(
            {"champion": champion, "win_rate": win_rate, "pick_rate": pick_rate, "ban_rate": ban_rate, "games": games}
        )
    return entries


def extract_row_number(text: str) -> float | None:
    """
    Parse the first numeric value in a row cell.
    """
    match = re.search(r"\d+(?:\.\d+)?", text)

    if match is None:
        return None
    return float(match.group())


def normalize_tierlist_champion(name: str) -> str | None:
    """
    Match a tier-list champion name to a supported champion.
    """
    normalized_input = normalize_name(name)

    for champion in CHAMPIONS:
        if normalize_name(champion) == normalized_input:
            return champion
    return None


def extract_games_from_row(text: str) -> int | None:
    """
    Parse the game count from a row cell.
    """
    match = re.search(r"[\d,]+", text)

    if match is None:
        return None
    return int(match.group().replace(",", ""))


def normalize_champion_slug(champion: str) -> str:
    """
    Convert a champion name to its LoLalytics URL slug.
    """
    special_names = {
        "AurelionSol": "aurelionsol",
        "Belveth": "belveth",
        "Chogath": "chogath",
        "DrMundo": "drmundo",
        "JarvanIV": "jarvaniv",
        "Kaisa": "kaisa",
        "Khazix": "khazix",
        "KogMaw": "kogmaw",
        "KSante": "ksante",
        "LeeSin": "leesin",
        "MasterYi": "masteryi",
        "MissFortune": "missfortune",
        "MonkeyKing": "wukong",
        "Nunu": "nunu",
        "RekSai": "reksai",
        "TahmKench": "tahmkench",
        "TwistedFate": "twistedfate",
        "Velkoz": "velkoz",
        "XinZhao": "xinzhao",
    }

    if champion in special_names:
        return special_names[champion]
    return champion.lower()


def extract_patch(text: str) -> str | None:
    """
    Extract the patch number from page text.
    """
    match = re.search(r"\bPatch\s+(\d+\.\d+)\b", text, re.IGNORECASE)

    if match is None:
        return None
    return match.group(1)


def extract_percentage(text: str, label: str) -> float | None:
    """
    Extract the percentage associated with a statistic label.
    """
    pattern = rf"(\d+(?:\.\d+)?)\s*%\s*{re.escape(label)}"
    match = re.search(pattern, text, re.IGNORECASE)

    if match is None:
        return None
    return float(match.group(1))


def extract_games(text: str) -> int | None:
    """
    Extract the total game count from page text.
    """
    match = re.search(r"Ban Rate\s+([\d,]+)\s+Games", text, re.IGNORECASE)

    if match is None:
        return None
    return int(match.group(1).replace(",", ""))


def extract_skill_order(text: str) -> dict:
    """
    Extract the skill leveling sequence from page text.
    """
    section_match = re.search(r"Skill Order(.*?)Primary Runes", text, re.IGNORECASE)

    if section_match is None:
        return {}
    section = section_match.group(1)
    ability_matches = list(re.finditer(r"\b([QWER])\b\s+Loading\.\.\.", section))
    result = {"Q": [], "W": [], "E": [], "R": []}

    for index, match in enumerate(ability_matches):
        ability = match.group(1)
        start = match.end()
        end = ability_matches[index + 1].start() if index + 1 < len(ability_matches) else len(section)
        levels = re.findall(r"\b(?:[1-9]|1[0-8])\b", section[start:end])
        result[ability] = [int(level) for level in levels]
    return result


def extract_all_matchups(text: str) -> dict:
    """
    Extract matchup win rates and game counts from page text.
    """
    matchups = {}
    table_start = text.find("Name WR vs All Champs")

    if table_start == -1:
        return matchups
    table_text = text[table_start:]
    pattern = re.compile(
        r"([A-Za-z][A-Za-z0-9' .\-]*?)\s+"
        r"(\d+(?:\.\d+)?)\s*%\s*VS\s+"
        r"Δ\s*1\s+[+\-]?\d+(?:\.\d+)?\s*"
        r"•\s*Δ\s*2\s+[+\-]?\d+(?:\.\d+)?\s+"
        r"\d+(?:\.\d+)?\s*%\s*VS\s+"
        r"([\d,]+)\s+Games\s+vs\s+",
        re.IGNORECASE,
    )

    for match in pattern.finditer(table_text):
        champion_name = normalize_matchup_name(match.group(1).strip())

        if champion_name is None:
            continue
        matchups[champion_name] = {"win_rate": float(match.group(2)), "games": int(match.group(3).replace(",", ""))}
    return matchups


def normalize_matchup_name(name: str) -> str | None:
    """
    Match a matchup name to a supported champion.
    """
    normalized_input = normalize_name(name)

    for champion in CHAMPIONS:
        if normalize_name(champion) == normalized_input:
            return champion
    return None


def normalize_name(name: str) -> str:
    """
    Normalize a name for consistent matching.
    """
    return name.lower().replace(" ", "").replace("'", "").replace(".", "").replace("-", "")
