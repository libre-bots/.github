import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from next_version import next_version

TODAY = date(2026, 11, 25)


@pytest.mark.parametrize(
    ("tags", "head_tags", "bump", "prerelease", "scheme", "expected"),
    [
        ([], [], "minor", False, "semver", "v0.1.0"),
        (["v0.1.0"], [], "patch", False, "semver", "v0.1.1"),
        (["v0.1.0"], [], "major", False, "semver", "v0.2.0"),
        (["v1.2.3"], [], "major", False, "semver", "v2.0.0"),
        (["v1.2.3"], [], "minor", True, "semver", "v1.3.0-rc.1"),
        (["v1.2.3", "v1.3.0-rc.1"], [], "minor", True, "semver", "v1.3.0-rc.2"),
        (["v1.2.3", "v1.3.0-rc.2"], [], "minor", False, "semver", "v1.3.0"),
        (["v1.2.3", "v1.3.0"], ["v1.3.0"], "patch", False, "semver", "v1.3.0"),
        (["v1.2.3", "junk", "release-1"], [], "patch", False, "semver", "v1.2.4"),
        (["v1.2.3", "v1.3.0-rc.1"], ["v1.3.0-rc.1"], "minor", True, "semver", "v1.3.0-rc.1"),
        (["v01.2.3"], ["v01.2.3"], "patch", False, "semver", "v0.0.1"),
        (["v2026.11.0"], ["v2026.11.0"], "patch", False, "calver", "v2026.11.0"),
        (["v2026.011.1"], [], "patch", False, "calver", "v2026.11.0"),
        ([], [], "patch", False, "calver", "v2026.11.0"),
        (["v2026.11.0"], [], "patch", False, "calver", "v2026.11.1"),
        (["v2026.10.3"], [], "patch", False, "calver", "v2026.11.0"),
        (["v2026.10.3"], ["v2026.10.3"], "patch", False, "calver", "v2026.10.3"),
        (["v2026.10.3"], [], "", False, "calver", "v2026.11.0"),
    ],
)
def test_next_version(tags, head_tags, bump, prerelease, scheme, expected):
    result = next_version(tags, head_tags, bump, prerelease, scheme, TODAY)
    assert result.tag == expected


def test_previous_tag_spans_candidates():
    result = next_version(["v1.2.3", "v1.3.0-rc.2"], [], "minor", False, "semver", TODAY)
    assert result.previous_tag == "v1.2.3"


def test_previous_tag_of_candidate_is_newest_tag():
    result = next_version(["v1.2.3", "v1.3.0-rc.1"], [], "minor", True, "semver", TODAY)
    assert result.previous_tag == "v1.3.0-rc.1"


def test_previous_tag_empty_without_tags():
    assert next_version([], [], "minor", False, "semver", TODAY).previous_tag == ""


def test_previous_tag_on_rerun():
    result = next_version(["v1.2.3", "v1.3.0"], ["v1.3.0"], "patch", False, "semver", TODAY)
    assert result.previous_tag == "v1.2.3"


def test_python_version():
    result = next_version(["v1.2.3", "v1.3.0-rc.1"], [], "minor", True, "semver", TODAY)
    assert result.semver == "1.3.0-rc.2"
    assert result.python == "1.3.0rc2"
    assert result.prerelease


def test_calver_rerun_keeps_previous_tag_across_months():
    result = next_version(["v2026.9.0", "v2026.10.3"], ["v2026.10.3"], "", False, "calver", TODAY)
    assert result.tag == "v2026.10.3"
    assert result.previous_tag == "v2026.9.0"


def test_semver_requires_bump():
    with pytest.raises(ValueError):
        next_version([], [], "", False, "semver", TODAY)


def test_unknown_bump_fails():
    with pytest.raises(ValueError):
        next_version([], [], "huge", False, "semver", TODAY)


def test_calver_rejects_prerelease():
    with pytest.raises(ValueError):
        next_version(["v2026.10.3"], [], "", True, "calver", TODAY)


@pytest.mark.parametrize(
    "junk", ["v1.2", "v01.2.3", "v1.2.3-rc.x", "v1.3.0-rc.007", "v1.3.0-rc.0", "v\u0661.2.3"]
)
def test_malformed_tags_are_ignored(junk):
    result = next_version(["v1.2.3", junk], [], "patch", False, "semver", TODAY)
    assert result.tag == "v1.2.4"
    assert result.previous_tag == "v1.2.3"


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-c", "tag.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True,
    )


def test_cli_writes_outputs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "one")
    _git(repo, "tag", "v0.1.0")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "two")
    out = tmp_path / "out.txt"
    env = {**os.environ, "GITHUB_OUTPUT": str(out)}
    script = Path(__file__).parent / "next_version.py"
    lines = [
        "tag=v0.1.1",
        "version=0.1.1",
        "python-version=0.1.1",
        "previous-tag=v0.1.0",
        "prerelease=false",
    ]
    for runs in (1, 2):
        subprocess.run(
            [sys.executable, str(script), "--bump", "patch"],
            cwd=repo, env=env, check=True, capture_output=True,
        )
        assert out.read_text().splitlines() == lines * runs


def test_cli_calver_without_bump(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "one")
    script = Path(__file__).parent / "next_version.py"
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    result = subprocess.run(
        [sys.executable, str(script), "--scheme", "calver"],
        cwd=repo, env=env, check=True, capture_output=True, text=True,
    )
    assert "prerelease=false" in result.stdout.splitlines()
