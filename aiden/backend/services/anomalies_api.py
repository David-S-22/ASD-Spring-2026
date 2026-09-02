from typing import List

from requests import get, post

from shared.backend import dto
from .. import config
from ..helpers import deserialise_or_abort, serialise


def get_all_anomalies() -> List[dto.Anomaly]:
    resp = get(_url("/"))
    resp.raise_for_status()

    return [deserialise_or_abort(dto.Anomaly, item) for item in resp.json()]

def create_anomaly(anomaly: dto.Anomaly) -> dto.Anomaly:
    resp = post(_url("/"), json=serialise(anomaly))
    resp.raise_for_status()

    return deserialise_or_abort(dto.Anomaly, resp.json())

def _url(path: str) -> str:
    return config.ANOMALIES_DB_URL + path
