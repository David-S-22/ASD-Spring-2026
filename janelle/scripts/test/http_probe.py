"""Small standard-library helpers for Janelle HTTP evidence probes."""

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProbeError(RuntimeError):
    """Raised when a probed endpoint does not satisfy its contract."""


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def normalize_date(value):
    if not isinstance(value, str):
        raise ProbeError(f"expected a date string, received {value!r}")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError) as error:
            raise ProbeError(f"could not parse date {value!r}") from error
    return parsed.date().isoformat()


def request_json(
    records,
    method,
    url,
    *,
    payload=None,
    expected=(200,),
    timeout=10,
):
    encoded = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        url,
        data=encoded,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    started_at = perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except HTTPError as error:
        status = error.code
        body = error.read()
    except URLError as error:
        raise ProbeError(f"{method} {url} failed: {error.reason}") from error

    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    parsed = None
    if body:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body.decode("utf-8", errors="replace")

    records.append({
        "method": method,
        "url": url,
        "status": status,
        "duration_ms": duration_ms,
    })
    if status not in expected:
        raise ProbeError(
            f"{method} {url} returned {status}, expected {expected}: {parsed}"
        )
    return parsed


def wait_for(url, timeout_seconds=45):
    deadline = perf_counter() + timeout_seconds
    last_error = None
    while perf_counter() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError) as error:
            last_error = error
        sleep(0.5)
    raise ProbeError(f"{url} was not ready: {last_error}")


def write_report(report, output_path):
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{rendered}\n", encoding="utf-8")
