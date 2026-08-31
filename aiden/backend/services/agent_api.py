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
You are the FIRST line of screening. A second, stricter reviewer will double-check anything you flag, so you should lean towards flagging anything that looks even somewhat unusual. Prefer false positives over missing a genuine anomaly.

You have these fields:

- id: the unique transaction identifier
- amount: the transaction amount
- merchant: the merchant name
- date: the transaction timestamp

Use a simple Plan → Act → Observe → Act process:

1. PLAN
   Identify which properties of the transaction could indicate an anomaly:
   - unusually large or round amounts (e.g. very high values, or suspiciously round numbers)
   - cash-like, high-risk, generic, or unfamiliar merchant names (e.g. ATMs, cash transfers, gift cards, crypto, vague names)
   - unusual or inconsistent date/time information (e.g. odd hours, future dates)
   - combinations of the above that together look anomalous

2. ACT
   Analyze the transaction using only the supplied properties and decide whether it is plausibly unusual or suspicious.

3. OBSERVE
   Re-read your reasoning. If your explanation describes ANY unusual, risky, or noteworthy characteristic, then the transaction IS suspicious and you MUST set "is_suspicious": true.
   Never describe something as unusual or risky while also marking it not suspicious — that is a contradiction.

4. ACT
   Make a final determination, erring on the side of flagging.

Guidance:
- A large amount is a legitimate reason to flag a transaction.
- A cash-like, generic, or unfamiliar merchant is a legitimate reason to flag a transaction.
- Only mark a transaction not suspicious when nothing about the supplied fields stands out as unusual.
- Do not claim fraud as a fact and do not invent missing context; describe only what the supplied fields show.
- Keep the explanation concise and factual.

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

"""

_review_system_prompt = """

You are a transaction anomaly-review VERIFIER.
Another agent has already inspected a single financial transaction and claimed it is suspicious, providing a reason.
Your task is to critically judge whether that claim is ACCURATE, based ONLY on the transaction fields and the reason provided.

You are given:

- The original transaction, with these fields:
  - id: the unique transaction identifier
  - amount: the transaction amount
  - merchant: the merchant name
  - date: the transaction timestamp
- The first agent's finding:
  - agent_reason_suspected: the reason the first agent believes the transaction is suspicious

Evaluate the finding critically:

1. Does the stated reason actually follow from the supplied transaction fields (amount, merchant, date)?
2. Characterising the supplied fields themselves IS allowed and is NOT invented context.
   For example, describing the merchant name "QuickCash ATM" as cash-like, ATM-related, or
   generic is a valid interpretation of the supplied merchant field. Likewise, calling a large
   amount "unusually large" is valid. Do NOT reject these as invented.
3. The finding relies on INVENTED context only if it asserts facts that are NOT any of the four
   supplied fields — for example the customer's history, location, income, expected spend,
   previous transactions, or account details. Reject the finding only in that case.
4. A large amount, a cash-like or unfamiliar merchant, or an odd date are each, on their own,
   legitimate and sufficient grounds to uphold a finding. You do NOT need corroborating evidence.
5. Uphold the finding whenever its reason is grounded in the supplied fields and points to a
   plausibly unusual characteristic. Reject it only when the reason is fabricated, contradicts
   the fields, or describes nothing unusual at all.

Important rules:
- Lean towards upholding findings that are grounded in the supplied fields.
- Interpreting the merchant name, amount, or date is grounding, not invention.
- Do not invent missing context of your own.
- Do not claim fraud as a fact.

Return ONLY valid JSON matching this schema:

{
  "is_accurate": boolean,
  "review_reason": string
}

Set "is_accurate": true only when the first agent's finding is well supported.
Set "is_accurate": false otherwise, and briefly explain why in "review_reason".

Do not return Markdown, code fences, commentary, or any additional fields.
"""

_review_user_prompt = """

Verify the following anomaly finding.

Transaction:
{0}

First agent's finding:
{1}

Determine whether the first agent's finding is accurate according to your instructions.

"""

class CouldNotParseAgentResponseException(Exception):
    pass

def review_new_transaction(transaction: dto.Transaction, all_transactions: List[dto.Transaction]) -> Optional[dto.Anomaly]:
    iteration = 1
    serialised = serialise(transaction)
    detect_user_prompt = _detect_user_prompt.format(serialised)
    impl_model = get_env("OLLAMA_IMPLEMENTATION_MODEL")
    # TODO: fill in transactions from all_transactions as additional context

    current_app.logger.info("Scan new transaction %s", serialised)

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

        # TODO: have senior model review it

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

@dataclass(frozen=True)
class ReviewFinding:
    is_suspicious: bool
    agent_reason_suspected: str

def parse_review_finding(model_response: str) -> Optional[ReviewFinding]:
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
