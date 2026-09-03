from typing import List, Optional

from requests import get, post

from shared.backend import dto
from ..helpers import deserialise_or_abort, serialise, get_env


def get_all_anomalies() -> List[dto.Anomaly]:
    resp = get(_url("/"))
    resp.raise_for_status()

    return [deserialise_or_abort(dto.Anomaly, item) for item in resp.json()]

def get_anomaly_by_transaction_id(transaction_id: int) -> Optional[dto.Anomaly]:
    resp = get(_url(f"/by-transaction/{transaction_id}"))

    if resp.status_code == 404:
        return None

    resp.raise_for_status()

    return deserialise_or_abort(dto.Anomaly, resp.json())

def create_anomaly(anomaly: dto.Anomaly) -> dto.Anomaly:
    resp = post(_url("/"), json=serialise(anomaly))
    resp.raise_for_status()

    return deserialise_or_abort(dto.Anomaly, resp.json())

def _url(path: str) -> str:
    return get_env("ANOMALIES_DB_URL") + path
