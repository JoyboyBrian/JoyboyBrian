#!/usr/bin/env python3
"""Generate the light and dark SVGs used by the profile README."""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from .github_stats import LocStats, collect_loc_stats, tokens_from_environment
except ImportError:  # Support `python scripts/update_profile.py`.
    from github_stats import LocStats, collect_loc_stats, tokens_from_environment


ROOT = Path(__file__).resolve().parents[1]
AVATAR_PATH = ROOT / "assets" / "avatar.txt"
USERNAME = os.environ.get("PROFILE_USERNAME", "JoyboyBrian")

CARD_WIDTH = 985
CARD_HEIGHT = 530
AVATAR_X = 15
TEXT_X = 390
TOML_COLUMNS = 69
CHAR_WIDTH = 8.3

# Static profile details. GitHub statistics are fetched at runtime.
PROFILE = {
    "name": "Zhengyang (Brian) Guo",
    "birthday": date(1999, 10, 5),
    "company": "Osmosis AI",
    "role": "Software Engineer",
    "location": "San Francisco, CA",
    "focus": "RL, developer tools",
    "os": "macOS, iOS, Linux",
    "ide": "Cursor",
    "languages_programming": "Python, TypeScript",
    "languages_computer": "Markdown, SQL, LaTeX, JSON, YAML",
    "languages_real": "Mandarin, English",
    "tools_ai": "Codex, Claude Code",
    "frameworks": "OpenAI Agents, Strands, Harbor",
    "stack_application": "Next.js, React, FastAPI",
    "stack_infrastructure": "AWS, EKS, Docker, SkyPilot",
    "stack_data": "PostgreSQL, Temporal",
    "website_company": "osmosis.ai",
    "website_personal": "zhengyang.sh",
    "linkedin": "linkedin.com/in/zhengyang-guo",
    "email": "zhengyang.brian.guo@gmail.com",
}

THEMES = {
    "dark_mode.svg": {
        "background": "#161b22",
        "text": "#c9d1d9",
        "muted": "#616e7f",
        "key": "#ffa657",
        "value": "#a5d6ff",
        "add": "#3fb950",
        "delete": "#f85149",
    },
    "light_mode.svg": {
        "background": "#f6f8fa",
        "text": "#24292f",
        "muted": "#c2cfde",
        "key": "#953800",
        "value": "#0a3069",
        "add": "#1a7f37",
        "delete": "#cf222e",
    },
}


def request(url: str, *, token: str | None = None, data: bytes | None = None) -> bytes:
    """Fetch a GitHub REST or GraphQL API URL."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub request failed ({error.code}): {message}"
        ) from error


def request_json(
    url: str,
    *,
    token: str | None = None,
    data: dict[str, Any] | None = None,
) -> Any:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    return json.loads(request(url, token=token, data=body))


def get_profile(token: str | None) -> dict[str, Any]:
    username = urllib.parse.quote(USERNAME)
    return request_json(f"https://api.github.com/users/{username}", token=token)


def get_repositories(token: str | None) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    username = urllib.parse.quote(USERNAME)
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {"per_page": 100, "page": page, "type": "owner", "sort": "updated"}
        )
        batch = request_json(
            f"https://api.github.com/users/{username}/repos?{query}", token=token
        )
        repositories.extend(batch)
        if len(batch) < 100:
            return repositories
        page += 1


def get_contributions(token: str | None) -> int | None:
    """Return contributions from the rolling last 365 days when a token is available."""
    if not token:
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365)
    payload = {
        "query": """
            query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                  contributionCalendar { totalContributions }
                }
              }
            }
        """,
        "variables": {
            "login": USERNAME,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
    }
    try:
        response = request_json(
            "https://api.github.com/graphql", token=token, data=payload
        )
        if response.get("errors"):
            raise RuntimeError(json.dumps(response["errors"]))
        return int(
            response["data"]["user"]["contributionsCollection"]["contributionCalendar"][
                "totalContributions"
            ]
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        print(f"warning: contribution count unavailable: {error}", file=sys.stderr)
        return None


def load_ascii_avatar() -> list[str]:
    """Load the hand-approved ASCII portrait used by both themes."""
    if not AVATAR_PATH.exists():
        raise FileNotFoundError(f"{AVATAR_PATH} is missing")

    lines = AVATAR_PATH.read_text(encoding="utf-8").splitlines()
    if not lines or not any(line.strip() for line in lines):
        raise ValueError(f"{AVATAR_PATH} does not contain an ASCII portrait")
    return lines


def add_months(value: date, months: int) -> date:
    """Return a date shifted by whole calendar months, clamping month-end days."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def age_parts(birthday: date, today: date | None = None) -> tuple[int, int, int]:
    """Calculate elapsed calendar years, months, and days since a birthday."""
    today = today or date.today()
    if today < birthday:
        raise ValueError("birthday cannot be in the future")

    years = today.year - birthday.year
    anniversary = add_months(birthday, years * 12)
    if anniversary > today:
        years -= 1
        anniversary = add_months(birthday, years * 12)

    months = 0
    while add_months(anniversary, months + 1) <= today:
        months += 1
    days = (today - add_months(anniversary, months)).days
    return years, months, days


def format_age(birthday: date, today: date | None = None) -> str:
    values = age_parts(birthday, today)
    units = ("year", "month", "day")
    return ", ".join(
        f"{value} {unit}{'' if value == 1 else 's'}"
        for value, unit in zip(values, units)
    )


def render_text(
    text: str,
    y: int,
    column: int,
    class_name: str | None = None,
) -> str:
    class_attribute = f' class="{class_name}"' if class_name else ""
    x = TEXT_X + column * CHAR_WIDTH
    return (
        f'<text x="{x:.1f}" y="{y}"{class_attribute}>'
        f"{html.escape(text)}</text>"
    )


def toml_string(value: str) -> str:
    """Return a TOML-compatible basic string."""
    return json.dumps(value, ensure_ascii=False)


def toml_array(value: str) -> str:
    items = (item.strip() for item in value.split(","))
    return f"[{', '.join(toml_string(item) for item in items)}]"


def toml_integer(value: int | None) -> str:
    return toml_string("N/A") if value is None else f"{value:_}"


def render_toml_section(name: str, y: int) -> str:
    return render_text(f"[brian.{name}]", y, 0, "section")


def render_toml_assignment(
    key: str, value: str, y: int, *, equals_column: int
) -> str:
    if len(key) >= equals_column:
        raise ValueError(f"TOML key is too long for its section: {key}")

    padding = " " * (equals_column - len(key))
    line_length = equals_column + 2 + len(value)
    if line_length > TOML_COLUMNS:
        raise ValueError(f"TOML line is too wide ({line_length} columns): {key}")

    return "\n".join(
        [
            render_text(key, y, 0, "key"),
            render_text(f"{padding}= ", y, len(key), "operator"),
            render_text(value, y, equals_column + 2, "value"),
        ]
    )


def render_svg(
    theme: dict[str, str],
    ascii_art: list[str],
    profile: dict[str, Any],
    repositories: list[dict[str, Any]],
    contributions: int | None,
    loc_stats: LocStats | None,
) -> str:
    stars = (
        loc_stats.stars
        if loc_stats is not None
        else sum(repository.get("stargazers_count", 0) for repository in repositories)
    )
    repository_count = (
        loc_stats.owned_repositories
        if loc_stats is not None
        else profile.get("public_repos")
    )
    github_stats = (
        "{ "
        f"repos={toml_integer(repository_count)}, "
        f"stars={toml_integer(stars)}, "
        f"contrib={toml_integer(contributions)}, "
        f"followers={toml_integer(profile.get('followers'))}"
        " }"
    )
    github_loc = (
        toml_string("N/A")
        if loc_stats is None
        else (
            "{ "
            f"net={toml_integer(loc_stats.net)}, "
            f"additions={toml_integer(loc_stats.additions)}, "
            f"deletions={toml_integer(loc_stats.deletions)}"
            " }"
        )
    )
    sections = [
        (
            "system",
            [
                ("os", toml_array(PROFILE["os"])),
                ("uptime", toml_string(format_age(PROFILE["birthday"]))),
                ("host", toml_string(PROFILE["company"])),
                ("kernel", toml_string(PROFILE["role"])),
                (
                    "location",
                    toml_string(profile.get("location") or PROFILE["location"]),
                ),
            ],
        ),
        (
            "developer",
            [
                ("focus", toml_array(PROFILE["focus"])),
                ("ide", toml_string(PROFILE["ide"])),
                (
                    "languages.programming",
                    toml_array(PROFILE["languages_programming"]),
                ),
                (
                    "languages.computer",
                    toml_array(PROFILE["languages_computer"]),
                ),
                ("languages.real", toml_array(PROFILE["languages_real"])),
                ("tools.ai", toml_array(PROFILE["tools_ai"])),
                ("frameworks", toml_array(PROFILE["frameworks"])),
            ],
        ),
        (
            "stack",
            [
                ("application", toml_array(PROFILE["stack_application"])),
                (
                    "infrastructure",
                    toml_array(PROFILE["stack_infrastructure"]),
                ),
                ("data", toml_array(PROFILE["stack_data"])),
            ],
        ),
        (
            "contact",
            [
                (
                    "website",
                    "{ "
                    f"personal={toml_string(PROFILE['website_personal'])}, "
                    f"company={toml_string(PROFILE['website_company'])}"
                    " }",
                ),
                ("linkedin", toml_string(PROFILE["linkedin"])),
                ("email", toml_string(PROFILE["email"])),
            ],
        ),
        ("github", [("stats", github_stats), ("loc", github_loc)]),
    ]

    avatar_columns = max(len(line) for line in ascii_art)
    avatar_rows = len(ascii_art)
    avatar_line_height = min(20.0, (CARD_HEIGHT - 40) / max(1, avatar_rows - 1))
    avatar_font_size = min(
        16.0,
        (TEXT_X - AVATAR_X - 15) / max(1, avatar_columns) / 0.61,
        avatar_line_height * 0.83,
    )
    avatar_spans = "\n".join(
        f'<tspan x="{AVATAR_X}" y="{24 + index * avatar_line_height:.1f}">'
        f"{html.escape(line)}</tspan>"
        for index, line in enumerate(ascii_art)
    )

    profile_lines: list[str] = []
    y = 30
    for section_name, fields in sections:
        profile_lines.append(render_toml_section(section_name, y))
        y += 20
        equals_column = max(len(key) for key, _ in fields) + 1
        for key, value in fields:
            profile_lines.append(
                render_toml_assignment(
                    key,
                    value,
                    y,
                    equals_column=equals_column,
                )
            )
            y += 20

    if y != CARD_HEIGHT:
        raise ValueError(f"TOML profile used an unexpected height: {y}px")

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="{CARD_WIDTH}px" height="{CARD_HEIGHT}px" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" font-size="16px" role="img" aria-labelledby="title desc">
<title id="title">{html.escape(PROFILE["name"])} GitHub profile</title>
<desc id="desc">Developer profile and live GitHub statistics with an ASCII avatar.</desc>
<style>
@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
.section {{fill: {theme["key"]}; font-weight: 700;}}
.key {{fill: {theme["key"]};}}
.operator {{fill: {theme["muted"]};}}
.value {{fill: {theme["value"]};}}
.cc {{fill: {theme["muted"]};}}
.add {{fill: {theme["add"]};}}
.delete {{fill: {theme["delete"]};}}
.ascii {{font-size: {avatar_font_size:.1f}px;}}
text, tspan {{white-space: pre;}}
</style>
<rect width="{CARD_WIDTH}px" height="{CARD_HEIGHT}px" fill="{theme["background"]}" rx="15"/>
<text x="{AVATAR_X}" y="24" fill="{theme["text"]}" class="ascii">
{avatar_spans}
</text>
<g fill="{theme["text"]}" class="toml" font-size="14px">
{chr(10).join(profile_lines)}
</g>
</svg>
'''


def main() -> None:
    tokens = tokens_from_environment()
    api_token = tokens[0] if tokens else None
    profile = get_profile(api_token)
    repositories = get_repositories(api_token)
    contributions = get_contributions(api_token)
    ascii_art = load_ascii_avatar()
    loc_stats: LocStats | None = None

    if tokens:
        cache_path = Path(os.environ.get("PROFILE_LOC_CACHE", ".cache/github-loc.json"))
        if not cache_path.is_absolute():
            cache_path = ROOT / cache_path
        loc_stats = collect_loc_stats(USERNAME, tokens, cache_path)
        print(
            "GitHub LOC: "
            f"{loc_stats.commits:,} commits across "
            f"{loc_stats.accessible_repositories:,} accessible repositories; "
            f"{loc_stats.refreshed_repositories:,} refreshed"
        )
    else:
        print(
            "warning: PROFILE_TOKENS is unavailable; GitHub LOC will show N/A",
            file=sys.stderr,
        )

    for filename, theme in THEMES.items():
        output = render_svg(
            theme,
            ascii_art,
            profile,
            repositories,
            contributions,
            loc_stats,
        )
        (ROOT / filename).write_text(output, encoding="utf-8")
        print(f"wrote {filename}")


if __name__ == "__main__":
    main()
