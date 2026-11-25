#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

NUM = r"(0|[1-9][0-9]*)"
TAG = re.compile(rf"^v{NUM}\.{NUM}\.{NUM}(?:-rc\.([1-9][0-9]*))?$", re.ASCII)
BUMPS = ("patch", "minor", "major")
SCHEMES = ("semver", "calver")


@dataclass(frozen=True)
class Version:
    tag: str
    semver: str
    python: str
    previous_tag: str
    prerelease: bool


def _parse(tag: str) -> tuple[int, int, int, int | None] | None:
    match = TAG.match(tag)
    if match is None:
        return None
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), None if rc is None else int(rc)


def _order(parsed: tuple[int, int, int, int | None]) -> tuple[int, int, int, float]:
    major, minor, patch, rc = parsed
    return major, minor, patch, float("inf") if rc is None else rc


def _format(core: tuple[int, int, int], rc: int | None) -> Version:
    base = ".".join(str(part) for part in core)
    if rc is None:
        return Version(f"v{base}", base, base, "", False)
    return Version(f"v{base}-rc.{rc}", f"{base}-rc.{rc}", f"{base}rc{rc}", "", True)


def _bumped(core: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    major, minor, patch = core
    if bump == "patch":
        return major, minor, patch + 1
    if bump == "minor" or major == 0:
        return major, minor + 1, 0
    return major + 1, 0, 0


def _previous(parsed: dict[str, tuple[int, int, int, int | None]], version: Version) -> str:
    current = _order(_parse(version.tag))
    older = [
        (_order(p), tag)
        for tag, p in parsed.items()
        if tag != version.tag and _order(p) < current and (version.prerelease or p[3] is None)
    ]
    return max(older)[1] if older else ""


def _with_previous(version: Version, previous: str) -> Version:
    return Version(version.tag, version.semver, version.python, previous, version.prerelease)


def _calver(tags: Iterable[str], head_tags: Iterable[str], today: date) -> Version:
    parsed = {t: p for t in tags if (p := _parse(t)) and p[3] is None and p[0] >= 2000}
    head = [t for t in head_tags if t in parsed]
    if head:
        tag = max(head, key=lambda t: parsed[t])
        version = _format(parsed[tag][:3], None)
    else:
        month = [p[2] for p in parsed.values() if p[:2] == (today.year, today.month)]
        version = _format((today.year, today.month, max(month) + 1 if month else 0), None)
    return _with_previous(version, _previous(parsed, version))


def next_version(
    tags: Iterable[str],
    head_tags: Iterable[str],
    bump: str,
    prerelease: bool,
    scheme: str,
    today: date,
) -> Version:
    """Return the version the next release of a repository gets."""
    if scheme not in SCHEMES:
        raise ValueError(f"unknown scheme: {scheme}")
    tags = list(tags)
    if scheme == "calver":
        if prerelease:
            raise ValueError("calver releases have no release candidates")
        return _calver(tags, head_tags, today)
    if bump not in BUMPS:
        raise ValueError(f"unknown bump: {bump}")

    parsed = {t: p for t in tags if (p := _parse(t))}
    head = [t for t in head_tags if t in parsed and (parsed[t][3] is not None) == prerelease]
    if head:
        tag = max(head, key=lambda t: _order(parsed[t]))
        major, minor, patch, rc = parsed[tag]
        version = _format((major, minor, patch), rc)
    else:
        stable = [p[:3] for p in parsed.values() if p[3] is None]
        core = _bumped(max(stable, default=(0, 0, 0)), bump)
        if prerelease:
            candidates = [p[3] for p in parsed.values() if p[:3] == core and p[3] is not None]
            version = _format(core, max(candidates, default=0) + 1)
        else:
            version = _format(core, None)
    return _with_previous(version, _previous(parsed, version))


def _git_tags(*args: str) -> list[str]:
    result = subprocess.run(["git", "tag", *args], capture_output=True, text=True, check=True)
    return result.stdout.split()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bump", default="")
    parser.add_argument("--prerelease", action="store_true")
    parser.add_argument("--scheme", default="semver")
    args = parser.parse_args()
    try:
        version = next_version(
            _git_tags("--list"),
            _git_tags("--points-at", "HEAD"),
            args.bump,
            args.prerelease,
            args.scheme,
            datetime.now(timezone.utc).date(),
        )
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    lines = (
        f"tag={version.tag}\n"
        f"version={version.semver}\n"
        f"python-version={version.python}\n"
        f"previous-tag={version.previous_tag}\n"
        f"prerelease={str(version.prerelease).lower()}\n"
    )
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
