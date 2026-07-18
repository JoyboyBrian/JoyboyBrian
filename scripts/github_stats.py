"""Collect cached GitHub contribution statistics through the GraphQL API."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


GRAPHQL_URL = "https://api.github.com/graphql"
CACHE_VERSION = 1
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}

REPOSITORIES_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    id
    repositories(
      first: 100
      after: $cursor
      affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      nodes {
        id
        nameWithOwner
        stargazerCount
        owner { login }
        defaultBranchRef {
          target { ... on Commit { oid } }
        }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

COMMIT_HISTORY_QUERY = """
query(
  $owner: String!
  $name: String!
  $authorId: ID!
  $cursor: String
) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $authorId}) {
            nodes { oid additions deletions }
            pageInfo { endCursor hasNextPage }
          }
        }
      }
    }
  }
}
"""


@dataclass
class RepositoryAccess:
    repository_id: str
    name_with_owner: str
    owner_login: str
    head_oid: str | None
    stargazer_count: int
    token_indexes: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class LocStats:
    accessible_repositories: int
    owned_repositories: int
    commits: int
    additions: int
    deletions: int
    stars: int
    refreshed_repositories: int = 0

    @property
    def net(self) -> int:
        return self.additions - self.deletions


class GraphQLClient:
    """Minimal GraphQL client that never logs its bearer token."""

    def __init__(self, token: str, *, attempts: int = 3) -> None:
        self._token = token
        self._attempts = attempts

    def execute(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(
            GRAPHQL_URL,
            data=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "JoyboyBrian-profile-readme",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        for attempt in range(self._attempts):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    result = json.loads(response.read())
                if result.get("errors"):
                    raise RuntimeError("GitHub GraphQL returned an error")
                return result["data"]
            except urllib.error.HTTPError as error:
                if (
                    error.code not in TRANSIENT_HTTP_CODES
                    or attempt + 1 == self._attempts
                ):
                    raise RuntimeError(
                        f"GitHub GraphQL request failed ({error.code})"
                    ) from error
            except urllib.error.URLError as error:
                if attempt + 1 == self._attempts:
                    raise RuntimeError("GitHub GraphQL request failed") from error
            time.sleep(2**attempt)

        raise AssertionError("unreachable")


def tokens_from_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """Read one or more tokens without ever echoing them."""
    environ = environ or os.environ
    raw_tokens = environ.get("PROFILE_TOKENS", "")
    if raw_tokens:
        candidates = raw_tokens.splitlines()
    else:
        candidates = [
            environ.get("PROFILE_TOKEN", ""),
            environ.get("GITHUB_TOKEN", ""),
        ]

    tokens: list[str] = []
    for candidate in candidates:
        token = candidate.strip()
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def discover_repositories(
    username: str,
    clients: list[GraphQLClient],
) -> tuple[str, dict[str, RepositoryAccess]]:
    """Discover owned, collaborator, and organization repositories per token."""
    author_id: str | None = None
    repositories: dict[str, RepositoryAccess] = {}

    for token_index, client in enumerate(clients):
        cursor: str | None = None
        while True:
            data = client.execute(
                REPOSITORIES_QUERY,
                {"login": username, "cursor": cursor},
            )
            user = data.get("user")
            if not user:
                raise RuntimeError(f"GitHub user {username!r} was not found")
            if author_id is None:
                author_id = user["id"]
            elif author_id != user["id"]:
                raise RuntimeError(
                    "GitHub tokens returned inconsistent user identities"
                )

            connection = user["repositories"]
            for node in connection["nodes"]:
                default_branch = node.get("defaultBranchRef")
                head_oid = (
                    default_branch["target"].get("oid") if default_branch else None
                )
                repository = repositories.get(node["id"])
                if repository is None:
                    repository = RepositoryAccess(
                        repository_id=node["id"],
                        name_with_owner=node["nameWithOwner"],
                        owner_login=node["owner"]["login"],
                        head_oid=head_oid,
                        stargazer_count=int(node["stargazerCount"]),
                    )
                    repositories[node["id"]] = repository
                repository.token_indexes.add(token_index)

            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

    if author_id is None:
        raise RuntimeError("no GitHub tokens were supplied")
    return author_id, repositories


def scan_repository(
    repository: RepositoryAccess,
    author_id: str,
    clients: list[GraphQLClient],
) -> dict[str, list[int]]:
    """Return additions and deletions for authored default-branch commits."""
    owner, name = repository.name_with_owner.split("/", 1)
    last_error: RuntimeError | None = None

    for token_index in sorted(repository.token_indexes):
        commits: dict[str, list[int]] = {}
        cursor: str | None = None
        client = clients[token_index]
        try:
            while True:
                data = client.execute(
                    COMMIT_HISTORY_QUERY,
                    {
                        "owner": owner,
                        "name": name,
                        "authorId": author_id,
                        "cursor": cursor,
                    },
                )
                default_branch = data["repository"].get("defaultBranchRef")
                if not default_branch:
                    return {}
                history = default_branch["target"]["history"]
                for node in history["nodes"]:
                    commits[node["oid"]] = [
                        int(node["additions"]),
                        int(node["deletions"]),
                    ]
                page_info = history["pageInfo"]
                if not page_info["hasNextPage"]:
                    return commits
                cursor = page_info["endCursor"]
        except (AttributeError, KeyError, TypeError, RuntimeError) as error:
            last_error = RuntimeError(
                "unable to read an accessible repository; verify Contents read access"
            )
            last_error.__cause__ = error

    if last_error:
        raise last_error
    raise RuntimeError("repository has no usable GitHub token")


def load_cache(cache_path: Path, author_id: str) -> dict[str, dict[str, Any]]:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION or data.get("author_id") != author_id:
            return {}
        repositories = data.get("repositories", {})
        if not isinstance(repositories, dict):
            raise TypeError
        return repositories
    except (json.JSONDecodeError, OSError, TypeError):
        print("warning: ignoring an invalid GitHub LOC cache", file=sys.stderr)
        return {}


def save_cache(
    cache_path: Path,
    author_id: str,
    repositories: dict[str, dict[str, Any]],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "author_id": author_id,
        "repositories": repositories,
    }
    temporary_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(cache_path)


def collect_loc_stats(
    username: str,
    tokens: list[str],
    cache_path: Path,
    *,
    client_factory: Callable[[str], GraphQLClient] = GraphQLClient,
) -> LocStats:
    """Collect deduplicated default-branch authored-commit totals."""
    if not tokens:
        raise RuntimeError("PROFILE_TOKENS is required for GitHub LOC statistics")

    clients = [client_factory(token) for token in tokens]
    author_id, repositories = discover_repositories(username, clients)
    previous_cache = load_cache(cache_path, author_id)
    next_cache: dict[str, dict[str, Any]] = {}
    refreshed = 0

    for repository_id, repository in repositories.items():
        cached = previous_cache.get(repository_id, {})
        if cached.get("head_oid") == repository.head_oid and isinstance(
            cached.get("commits"), dict
        ):
            commits = cached["commits"]
        elif repository.head_oid is None:
            commits = {}
        else:
            commits = scan_repository(repository, author_id, clients)
            refreshed += 1
        next_cache[repository_id] = {
            "head_oid": repository.head_oid,
            "commits": commits,
        }

    save_cache(cache_path, author_id, next_cache)

    unique_commits: dict[str, tuple[int, int]] = {}
    for repository in next_cache.values():
        for oid, totals in repository["commits"].items():
            value = (int(totals[0]), int(totals[1]))
            existing = unique_commits.setdefault(oid, value)
            if existing != value:
                raise RuntimeError("GitHub returned inconsistent commit statistics")

    additions = sum(value[0] for value in unique_commits.values())
    deletions = sum(value[1] for value in unique_commits.values())
    owned_repositories = sum(
        repository.owner_login.casefold() == username.casefold()
        for repository in repositories.values()
    )
    stars = sum(
        repository.stargazer_count
        for repository in repositories.values()
        if repository.owner_login.casefold() == username.casefold()
    )
    return LocStats(
        accessible_repositories=len(repositories),
        owned_repositories=owned_repositories,
        commits=len(unique_commits),
        additions=additions,
        deletions=deletions,
        stars=stars,
        refreshed_repositories=refreshed,
    )
