from typing import List

from requests import get

from shared.backend import dto
from ..helpers import deserialise_or_abort, get_env


def get_all_transactions() -> List[dto.Transaction]:
    resp = get(_url("/transactions"))
    resp.raise_for_status()

    return [deserialise_or_abort(dto.Transaction, item) for item in resp.json()]

def _url(path: str) -> str:
    return get_env("TRANSACTIONS_DB_URL") + path
