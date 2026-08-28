import os
import requests
from dataclasses import asdict
from typing import List
from shared.backend import dto
from ..helpers import serialise, deserialise_or_abort


def get_all_anomalies() -> List[dto.Anomaly]:
    resp = requests.get(url("/"))
    resp.raise_for_status()

    return [deserialise_or_abort(dto.Anomaly, item) for item in resp.json()]

def create_anomaly(anomaly: dto.Anomaly) -> dto.Anomaly:
    resp = requests.post(url("/"), json=serialise(anomaly))
    resp.raise_for_status()

    return deserialise_or_abort(dto.Anomaly, resp.json())

def url(path: str):
    return os.environ["ANOMALIES_DB_URL"] + path
