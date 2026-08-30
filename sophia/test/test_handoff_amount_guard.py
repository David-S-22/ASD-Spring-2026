"""Non-finite amounts in the Feature 4 handoff link must get the 422 error fragment, not a 500."""
import pytest

HANDOFF_QUERY = {
    "source": "f4",
    "alert_id": "7",
    "merchant": "Spotify",
    "amount": "12.99",
    "cadence": "monthly",
    "first_seen": "2026-05-01",
    "last_seen": "2026-08-01",
    "occurrences": "4",
}


def _handoff_query(**overrides):
    query = dict(HANDOFF_QUERY)
    query.update(overrides)
    return {key: value for key, value in query.items() if value is not None}


def _text(response):
    return response.get_data(as_text=True)


@pytest.mark.parametrize("amount", ["nan", "inf", "-inf"])
def test_handoff_subscription_non_finite_amount_is_rejected(live_client, amount):
    response = live_client.get("/ui/handoff/subscription", query_string=_handoff_query(amount=amount))
    assert response.status_code == 422
    assert 'class="error"' in _text(response)


def test_handoff_subscription_huge_finite_amount_still_accepted(live_client):
    response = live_client.get("/ui/handoff/subscription", query_string=_handoff_query(amount="999999.99"))
    assert response.status_code == 200
    assert 'value="999999.99"' in _text(response)
