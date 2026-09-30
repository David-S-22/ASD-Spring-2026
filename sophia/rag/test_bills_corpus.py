"""Unit tests for rendering bill records into corpus files: plain dicts, no network, no filesystem."""
import pytest

from sophia.rag import bills_corpus

SPOTIFY = {
    "id": 3, "name": "Spotify", "merchant": "Spotify AU", "amount_cents": 1399, "cadence": "monthly",
    "next_billing_date": "2026-08-16", "type": "subscription", "payment_method": "card", "status": "paid",
    "end_date": None, "exclude_from_plan": 0,
}
SPOTIFY_PAYMENTS = [
    {"bill_id": 3, "date": "2026-06-16", "amount_cents": 1399},
    {"bill_id": 3, "date": "2026-08-16", "amount_cents": 1399},
    {"bill_id": 3, "date": "2026-07-16", "amount_cents": 1399},
]
SPOTIFY_TEXT = """# Spotify (subscription)

- Merchant: Spotify AU
- Type: subscription
- Cadence: monthly
- Amount: $13.99
- Next billing date: 2026-08-16
- Status: paid
- Payment method: card
- Last payment: 2026-08-16 ($13.99)
- Open disputes: 0
"""


def test_render_bill_matches_the_contract():
    """A bill with payments and no disputes renders exactly the documented lines, latest payment last."""
    assert bills_corpus.render_bill(SPOTIFY, SPOTIFY_PAYMENTS, []) == SPOTIFY_TEXT


def test_render_bill_omits_lines_it_has_no_value_for():
    """No payment method and no payments leaves those lines out instead of printing None."""
    bill = dict(SPOTIFY, id=11, name="Share-house utilities kitty", payment_method=None)
    text = bills_corpus.render_bill(bill, [], [])
    assert "Payment method" not in text
    assert "Last payment" not in text
    assert "- Open disputes: 0" in text


def test_render_bill_counts_only_draft_and_sent_disputes():
    """A resolved dispute is not open."""
    disputes = [{"bill_id": 3, "status": "draft"}, {"bill_id": 3, "status": "sent"}, {"bill_id": 3, "status": "resolved"}]
    assert "- Open disputes: 2" in bills_corpus.render_bill(SPOTIFY, [], disputes)


def test_render_bill_shows_end_date_and_plan_exclusion_when_set():
    """An ended bill and a bill kept out of the plan each get one extra line."""
    text = bills_corpus.render_bill(dict(SPOTIFY, end_date="2026-09-16", exclude_from_plan=1), [], [])
    assert "- End date: 2026-09-16" in text
    assert text.endswith("- Excluded from the monthly plan: yes\n")


def test_file_name_is_the_id_and_a_slug_of_the_name():
    """Names become lower-case letters and digits joined by hyphens, after the bill id."""
    assert bills_corpus.file_name({"id": 10, "name": "Opal commute top-up"}) == "bill-10-opal-commute-top-up.md"
    assert bills_corpus.file_name({"id": 11, "name": "Share-house utilities kitty"}) == "bill-11-share-house-utilities-kitty.md"


def test_render_corpus_orders_files_by_bill_id():
    """Bills arrive in any order and come out by id, each rendered with only its own payments and disputes."""
    netflix = dict(SPOTIFY, id=4, name="Netflix", merchant="Netflix", amount_cents=2099, status="due")
    files = bills_corpus.render_corpus([netflix, SPOTIFY], SPOTIFY_PAYMENTS, [{"bill_id": 4, "status": "draft"}])
    assert list(files) == ["bill-3-spotify.md", "bill-4-netflix.md"]
    assert files["bill-3-spotify.md"] == SPOTIFY_TEXT
    assert "- Open disputes: 1" in files["bill-4-netflix.md"]
    assert "Last payment" not in files["bill-4-netflix.md"]


def test_render_corpus_rejects_a_file_over_the_chunk_cap():
    """A bill that would not fit in one chunk stops the build instead of being truncated."""
    with pytest.raises(ValueError):
        bills_corpus.render_corpus([dict(SPOTIFY, name="x" * bills_corpus.MAX_CHARS)], [], [])
