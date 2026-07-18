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
TEXT_COLUMNS = 59
CHAR_WIDTH = 9.5

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
    "website": "osmosis.ai",
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


def format_number(value: int | None) -> str:
    return "N/A" if value is None else f"{value:,}"


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


def render_divider(label: str, y: int, *, section: bool = False) -> str:
    heading = f"- {label}" if section else label
    dash_count = max(1, TEXT_COLUMNS - len(heading) - 5)
    line = f"{heading} -{'—' * dash_count}-—-"
    return f'<text x="{TEXT_X}" y="{y}">{html.escape(line)}</text>'


def render_text(
    text: str,
    y: int,
    column: int,
    class_name: str | None = None,
    *,
    text_anchor: str | None = None,
) -> str:
    class_attribute = f' class="{class_name}"' if class_name else ""
    anchor_attribute = f' text-anchor="{text_anchor}"' if text_anchor else ""
    x = TEXT_X + column * CHAR_WIDTH
    return (
        f'<text x="{x:.1f}" y="{y}"{class_attribute}{anchor_attribute}>'
        f"{html.escape(text)}</text>"
    )


def render_positioned_field(
    label: str, value: str, y: int, *, start_column: int, width: int
) -> str:
    fixed_width = len(label) + len(":") + 2 + len(value)
    leader = f" {'.' * max(1, width - fixed_width)} "
    colon_column = start_column + len(label)
    leader_column = colon_column + 1
    value_column = leader_column + len(leader)
    return "\n".join(
        [
            render_text(label, y, start_column, "key"),
            render_text(":", y, colon_column),
            render_text(leader, y, leader_column, "cc"),
            render_text(value, y, value_column, "value"),
        ]
    )


def render_field(label: str, value: str, y: int) -> str:
    return "\n".join(
        [
            render_text(". ", y, 0, "cc"),
            render_positioned_field(
                label, value, y, start_column=2, width=TEXT_COLUMNS - 2
            ),
        ]
    )


def render_right_aligned_field(
    label: str,
    value: str,
    y: int,
    *,
    start_column: int,
    end_column: int,
) -> str:
    """Render a field whose value ends at an exact SVG coordinate."""
    colon_column = start_column + len(label)
    leader_column = colon_column + 1
    leader_width = end_column - leader_column - len(value)
    leader = f" {'.' * max(1, leader_width - 2)} "
    return "\n".join(
        [
            render_text(label, y, start_column, "key"),
            render_text(":", y, colon_column),
            render_text(leader, y, leader_column, "cc"),
            render_text(
                value,
                y,
                end_column,
                "value",
                text_anchor="end",
            ),
        ]
    )


def render_stats_pair(left: tuple[str, str], right: tuple[str, str], y: int) -> str:
    return "\n".join(
        [
            render_text(". ", y, 0, "cc"),
            render_positioned_field(*left, y, start_column=2, width=31),
            render_text(" | ", y, 33),
            render_right_aligned_field(
                *right,
                y,
                start_column=36,
                end_column=TEXT_COLUMNS,
            ),
        ]
    )


def render_loc_stats(stats: LocStats | None, y: int) -> str:
    if stats is None:
        return render_field("GitHub LOC", "N/A", y)

    net = format_number(stats.net)
    additions = format_number(stats.additions)
    deletions = format_number(stats.deletions)
    suffix_width = len(additions) + len(deletions) + 9
    suffix_column = TEXT_COLUMNS - suffix_width
    fragments = [
        render_text(". ", y, 0, "cc"),
        render_right_aligned_field(
            "GitHub LOC",
            net,
            y,
            start_column=2,
            end_column=suffix_column,
        ),
        render_text(" (", y, suffix_column),
        render_text(additions, y, suffix_column + 2, "add"),
        render_text("++", y, suffix_column + 2 + len(additions), "add"),
        render_text(
            ", ",
            y,
            suffix_column + 4 + len(additions),
        ),
        render_text(
            deletions,
            y,
            suffix_column + 6 + len(additions),
            "delete",
        ),
        render_text(
            "--",
            y,
            suffix_column + 6 + len(additions) + len(deletions),
            "delete",
        ),
        render_text(
            ")",
            y,
            suffix_column + 8 + len(additions) + len(deletions),
        ),
    ]
    return "\n".join(fragments)


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
    fields = [
        ("OS", PROFILE["os"]),
        ("Uptime", format_age(PROFILE["birthday"])),
        ("Host", PROFILE["company"]),
        ("Kernel", PROFILE["role"]),
        ("Location", profile.get("location") or PROFILE["location"]),
        ("Focus", PROFILE["focus"]),
        ("IDE", PROFILE["ide"]),
        ("Languages.Programming", PROFILE["languages_programming"]),
        ("Languages.Computer", PROFILE["languages_computer"]),
        ("Languages.Real", PROFILE["languages_real"]),
        ("Tools.AI", PROFILE["tools_ai"]),
        ("Frameworks", PROFILE["frameworks"]),
        ("Stack.Application", PROFILE["stack_application"]),
        ("Stack.Infrastructure", PROFILE["stack_infrastructure"]),
        ("Stack.Data", PROFILE["stack_data"]),
    ]
    contacts = [
        ("Company.Website", PROFILE["website"]),
        ("LinkedIn", PROFILE["linkedin"]),
        ("Email", PROFILE["email"]),
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

    profile_lines = [render_divider("brian@github", 30)]
    profile_lines.extend(
        render_field(label, str(value), 50 + index * 20)
        for index, (label, value) in enumerate(fields)
    )
    profile_lines.append(render_divider("Contact", 350, section=True))
    profile_lines.extend(
        render_field(label, str(value), 370 + index * 20)
        for index, (label, value) in enumerate(contacts)
    )
    profile_lines.append(render_divider("GitHub Stats", 450, section=True))
    profile_lines.append(
        render_stats_pair(
            ("Repos", format_number(repository_count)),
            ("Stars", format_number(stars)),
            470,
        )
    )
    profile_lines.append(
        render_stats_pair(
            ("Contributions (365d)", format_number(contributions)),
            ("Followers", format_number(profile.get("followers"))),
            490,
        )
    )
    profile_lines.append(render_loc_stats(loc_stats, 510))

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
.key {{fill: {theme["key"]};}}
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
<g fill="{theme["text"]}">
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
