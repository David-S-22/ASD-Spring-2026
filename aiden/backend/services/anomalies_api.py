import os
import requests
from dataclasses import asdict
from typing import List
from shared.backend import dto
from ..helpers import deserialise_or_abort


def get_all_anomalies() -> List[dto.Anomaly]:
    resp = requests.get(url("/"))
    resp.raise_for_status()

    data = resp.json()
    assert isinstance(data, list)

    return data # TODO fix

def create_anomaly(anomaly: dto.Anomaly) -> dto.Anomaly:
    payload = asdict(anomaly)
    payload["id"] = str(payload["id"]) # TODO fix
    payload["transaction_id"] = str(payload["transaction_id"])

    resp = requests.post(url("/"), json=payload)
    resp.raise_for_status()

    return deserialise_or_abort(dto.Anomaly, resp.json())

def url(path: str):
    return os.environ["ANOMALIES_DB_URL"] + path
