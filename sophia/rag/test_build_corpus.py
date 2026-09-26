"""Tests for the corpus build command against the real bills-db app served on a temporary seeded database."""
import pytest

from sophia.backend import config
from sophia.rag import build_corpus

SEEDED_FILES = [
    "bill-1-rent.md", "bill-2-anytime-fitness.md", "bill-3-spotify.md", "bill-4-netflix.md",
    "bill-5-prime-video.md", "bill-6-gymco.md", "bill-7-home-internet.md", "bill-8-phone-plan.md",
    "bill-9-electricity.md", "bill-10-opal-commute-top-up.md", "bill-11-share-house-utilities-kitty.md",
    "bill-12-cloud-storage.md",
]


@pytest.fixture(scope="module")
def seed_api():
    """Point the bills-db client at a seeded database served for the whole module, then restore it."""
    live_url = config.BILLS_DB_API_URL
    with build_corpus.seed_database_api() as base_url:
        config.BILLS_DB_API_URL = base_url
        yield base_url
    config.BILLS_DB_API_URL = live_url


def bill_files(folder):
    """The bill file names in a folder, in bill id order."""
    return sorted((path.name for path in folder.glob("bill-*.md")), key=lambda name: int(name.split("-")[1]))


def test_build_writes_one_file_per_seeded_bill(seed_api, tmp_path):
    """The seed's twelve bills become twelve files named by id and slug."""
    assert build_corpus.main(["--out", str(tmp_path)]) == 0
    assert bill_files(tmp_path) == SEEDED_FILES
    assert (tmp_path / "bill-7-home-internet.md").read_text(encoding="utf-8").startswith("# Home internet (bill)\n")


def test_check_passes_right_after_a_build(seed_api, tmp_path):
    """A folder that matches a fresh build is fresh."""
    build_corpus.main(["--out", str(tmp_path)])
    assert build_corpus.main(["--out", str(tmp_path), "--check"]) == 0


def test_check_fails_when_a_file_was_edited(seed_api, tmp_path, capsys):
    """A hand edit makes the check fail and name the file."""
    build_corpus.main(["--out", str(tmp_path)])
    (tmp_path / "bill-3-spotify.md").write_text("# Spotify (subscription)\n\n- Amount: $0.00\n", encoding="utf-8")
    assert build_corpus.main(["--out", str(tmp_path), "--check"]) == 1
    assert "changed: bill-3-spotify.md" in capsys.readouterr().out


def test_check_fails_when_a_stale_file_is_present(seed_api, tmp_path, capsys):
    """A bill file with no bill behind it makes the check fail."""
    build_corpus.main(["--out", str(tmp_path)])
    (tmp_path / "bill-99-ghost.md").write_text("# Ghost (bill)\n", encoding="utf-8")
    assert build_corpus.main(["--out", str(tmp_path), "--check"]) == 1
    assert "stale: bill-99-ghost.md" in capsys.readouterr().out


def test_check_fails_when_a_file_is_missing(seed_api, tmp_path, capsys):
    """A deleted bill file makes the check fail."""
    build_corpus.main(["--out", str(tmp_path)])
    (tmp_path / "bill-4-netflix.md").unlink()
    assert build_corpus.main(["--out", str(tmp_path), "--check"]) == 1
    assert "missing: bill-4-netflix.md" in capsys.readouterr().out


def test_rebuild_removes_stale_files_after_writing(seed_api, tmp_path):
    """A rebuild drops stale bill files and leaves exactly the seeded twelve."""
    build_corpus.main(["--out", str(tmp_path)])
    (tmp_path / "bill-99-ghost.md").write_text("# Ghost (bill)\n", encoding="utf-8")
    assert build_corpus.main(["--out", str(tmp_path)]) == 0
    assert bill_files(tmp_path) == SEEDED_FILES


def test_from_seed_matches_a_build_from_the_api(seed_api, tmp_path):
    """--from-seed writes byte for byte what a live database holding the seed writes, and restores the client URL."""
    api_dir, seed_dir = tmp_path / "api", tmp_path / "seed"
    build_corpus.main(["--out", str(api_dir)])
    assert build_corpus.main(["--out", str(seed_dir), "--from-seed"]) == 0
    assert {p.name: p.read_bytes() for p in api_dir.iterdir()} == {p.name: p.read_bytes() for p in seed_dir.iterdir()}
    assert config.BILLS_DB_API_URL == seed_api
