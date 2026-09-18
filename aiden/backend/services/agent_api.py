from datetime import datetime
from json import JSONDecodeError
from typing import Optional
from dataclasses import dataclass

from flask import current_app

from shared.backend import dto
from ..config import config
from .ollama_api import prompt
from ..helpers import serialise

_detect_system_prompt = """

You are a skeptical transaction anomaly-detection agent.
Your task is to decide whether a single financial transaction looks suspicious based ONLY on the information provided in the transaction.
Everything you flag is shown directly to the user for review. Because the user sees your findings, err on the side of caution: only flag a transaction when there is a clear, defensible reason, and keep your explanation accurate and easy for a person to verify. Avoid flooding the user with weak or speculative flags.
Today's date is {0}. Use this information when evaluating the transaction.

You have these fields:

- id: the unique transaction identifier
- amount: the transaction amount
- merchant: the merchant name
- description: the transaction description
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

Before evaluating the transaction, call both MCP tools:
- get_transactions_with_confirmed_anomalies: transactions the user agreed were suspicious.
- get_transactions_with_rejected_anomalies: transactions the user decided were not suspicious.
Use the confirmed results as positive examples and the rejected results as negative examples.
Use this feedback to align your judgement with the user's, but still evaluate the current transaction on its own merits.

Return ONLY valid JSON matching this schema:

{{
  "is_suspicious": boolean,
  "justification": string
}}

Always populate "justification" with a concise explanation of your decision — even when "is_suspicious" is false, briefly state why the transaction looks legitimate. Never leave it empty.

Do not return Markdown, code fences, commentary, or any additional fields.
"""

_detect_user_prompt = """

Review the following transaction. Determine whether this transaction is suspicious according to your instructions.

{0}
"""

class CouldNotParseAgentResponseException(Exception):
    pass

@dataclass(frozen=True)
class ReviewFinding:
    is_suspicious: bool
    justification: str

def review_new_transaction(
    transaction: dto.Transaction,
) -> Optional[dto.Anomaly]:
    iteration = 1
    serialised = serialise(transaction)
    detect_system_prompt = _detect_system_prompt.format(datetime.now().strftime("%Y-%m-%d"))
    detect_user_prompt = _detect_user_prompt.format(serialised)
    review_finding: Optional[ReviewFinding] = None

    current_app.logger.info("Scan new transaction %s", serialised)

    while iteration < 5:
        temperature = 0.2 * iteration # increase as it gets iterated
        response = prompt(
            system_prompt=detect_system_prompt,
            user_prompt=detect_user_prompt,
            model=config.OLLAMA_MODEL,
            temperature=temperature,
            output_tokens=500)

        if (candidate := parse_review_finding(response)) is None:
            current_app.logger.info("Response is not acceptable json %s", response)
            iteration += 1
            continue

        review_finding = candidate
        current_app.logger.info("Response was formatted into finding %s", review_finding)
        break

    if review_finding is None:
        raise CouldNotParseAgentResponseException()

    if not review_finding.is_suspicious:
        current_app.logger.info("Not classified suspicious, no anomaly. Justification: %s", review_finding.justification)
        return None

    return dto.Anomaly(
        id=0,
        transaction_id=transaction.id,
        agent_reason_suspected=review_finding.justification,
        is_confirmed_by_user=None
    )

def parse_review_finding(model_response: str) -> Optional[ReviewFinding]:
    """Determines if the model response was a valid format"""

    try:
        data = current_app.json.loads(model_response)
    except JSONDecodeError:
        return None

    if (
        isinstance(is_suspicious := data.get("is_suspicious"), bool) and
        isinstance(justification := data.get("justification"), str)
    ):
        return ReviewFinding(is_suspicious, justification)

    return None
