from json import JSONDecodeError, loads
from typing import List, Optional, Tuple
from uuid import uuid4
from dataclasses import dataclass

from flask import current_app

from shared.backend import dto
from .ollama_api import prompt
from ..helpers import serialise, get_env

_detect_system_prompt = """

You are a skeptical transaction anomaly-detection agent.
Your task is to decide whether a single financial transaction looks suspicious based ONLY on the information provided in the transaction.
Everything you flag is shown directly to the user for review. Because the user sees your findings, err on the side of caution: only flag a transaction when there is a clear, defensible reason, and keep your explanation accurate and easy for a person to verify. Avoid flooding the user with weak or speculative flags.

You have these fields:

- id: the unique transaction identifier
- amount: the transaction amount
- merchant: the merchant name
- date: the transaction timestamp

Consider which properties of the transaction could indicate an anomaly:
- unusually large or round amounts (e.g. very high values, or suspiciously round numbers)
- cash-like, high-risk, generic, or unfamiliar merchant names (e.g. ATMs, cash transfers, gift cards, crypto, vague names)
- unusual or inconsistent date/time information (e.g. odd hours, future dates)
- combinations of the above that together look anomalous

Analyze the transaction using only the supplied properties and make a final determination. If your explanation describes a genuinely unusual, risky, or noteworthy characteristic, set "is_suspicious": true. Never describe something as unusual or risky while also marking it not suspicious — that is a contradiction.

Guidance:
- A large amount is a legitimate reason to flag a transaction.
- A cash-like, generic, or unfamiliar merchant is a legitimate reason to flag a transaction.
- Only mark a transaction not suspicious when nothing about the supplied fields stands out as unusual.
- Do not claim fraud as a fact and do not invent missing context; describe only what the supplied fields show.
- Keep the explanation concise and factual.

You may be given additional context describing prior findings the user has already reviewed:
- CONFIRMED entries are transactions the user agreed were genuinely suspicious. Treat similar transactions as more likely to be suspicious.
- DENIED entries are transactions the user decided were NOT suspicious (false positives). Treat similar transactions as more likely to be legitimate, and avoid flagging them for the same reasons.
Use this feedback to align your judgement with the user's, but still evaluate the current transaction on its own merits.

Return ONLY valid JSON matching this schema:

{
  "is_suspicious": boolean,
  "agent_reason_suspected": string
}

If the transaction is not suspicious, set:
"is_suspicious": false
and use an empty string for "agent_reason_suspected".

Do not return Markdown, code fences, commentary, or any additional fields.
"""

_detect_user_prompt = """

Review the following transaction. Determine whether this transaction is suspicious according to your instructions.

{0}
{1}
"""

_anomaly_context_prompt = """

Additional context — prior findings the user has already reviewed:
{0}
"""

class CouldNotParseAgentResponseException(Exception):
    pass

@dataclass(frozen=True)
class ReviewFinding:
    is_suspicious: bool
    agent_reason_suspected: str

def review_new_transaction(transaction: dto.Transaction, all_anomalies: List[dto.Anomaly]) -> Optional[dto.Anomaly]:
    iteration = 1
    serialised = serialise(transaction)
    anomaly_context = _build_anomaly_context(all_anomalies)
    detect_user_prompt = _detect_user_prompt.format(serialised, anomaly_context)
    impl_model = get_env("OLLAMA_IMPLEMENTATION_MODEL")

    current_app.logger.info("Scan new transaction %s", serialised)
    current_app.logger.info("Anomaly context: %s", anomaly_context)

    while iteration < 5:
        temperature = 0.2 * iteration # increase as it gets iterated
        response = prompt(
            system_prompt=_detect_system_prompt,
            user_prompt=detect_user_prompt,
            model=impl_model,
            temperature=temperature,
            output_tokens=500)

        if (review_finding := parse_review_finding(response)) is None:
            current_app.logger.info("Response is not acceptable json %s", response)
            continue

        current_app.logger.info("Response was formatted into finding %s", review_finding)

        break

    if review_finding is None:
        raise CouldNotParseAgentResponseException()

    if not review_finding.is_suspicious:
        current_app.logger.info("Not classified suspicious, no anomaly")
        return None

    return dto.Anomaly(
        id=uuid4(),
        transaction_id=transaction.id,
        agent_reason_suspected=review_finding.agent_reason_suspected,
        is_confirmed_by_user=None
    )

def _build_anomaly_context(all_anomalies: List[dto.Anomaly]) -> str:
    """Builds additional prompt context from anomalies the user has already reviewed.

    Only anomalies confirmed (True) or denied (False) by the user are included;
    anomalies still awaiting review (None) are ignored.
    """

    confirmed = [a for a in all_anomalies if a.is_confirmed_by_user is True]
    denied = [a for a in all_anomalies if a.is_confirmed_by_user is False]

    if not confirmed and not denied:
        return ""

    lines: List[str] = []

    for anomaly in confirmed:
        lines.append(f"- CONFIRMED suspicious: {anomaly.agent_reason_suspected}")

    for anomaly in denied:
        lines.append(f"- DENIED (not suspicious): {anomaly.agent_reason_suspected}")

    return _anomaly_context_prompt.format("\n".join(lines))

def parse_review_finding(model_response: str) -> Optional[ReviewFinding]:
    """Determines if the model response was a valid format"""

    try:
        data = current_app.json.loads(model_response)
    except JSONDecodeError:
        return None

    if (
        isinstance(is_suspicious := data.get("is_suspicious"), bool) and
        isinstance(agent_reason_suspected := data.get("agent_reason_suspected"), str)
    ):
        return ReviewFinding(is_suspicious, agent_reason_suspected)

    return None
