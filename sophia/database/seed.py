"""Idempotent demo seed data for the bills database, dated relative to DEMO_TODAY=2026-08-20."""
import json

# The trailing status value must equal engine/status.derive_status for the row's
# payments at DEMO_TODAY: reads never heal the cached column, only writes refresh it.
BILLS = [
    (1, "Rent", "Harbourview Realty", 110000, "monthly", "2026-09-01", "bill", "direct_debit", "manual", "2026-08-01", "2026-03-01", 1, "paid"),
    (2, "Anytime Fitness", "Anytime Fitness Ultimo", 1750, "fortnightly", "2026-08-18", "subscription", "direct_debit", "manual", "2026-05-01", "2026-03-10", 0, "paid"),
    (3, "Spotify", "Spotify AU", 1399, "monthly", "2026-08-16", "subscription", "card", "manual", "2026-08-16", "2026-02-16", 0, "paid"),
    (4, "Netflix", "Netflix", 2099, "monthly", "2026-09-02", "subscription", "card", "manual", None, "2026-08-19", 0, "due"),
    (5, "Prime Video", "Prime Video", 999, "monthly", "2026-08-24", "subscription", "card", "manual", None, "2026-08-17", 0, "due"),
    (6, "GymCo", "GymCo", 2499, "monthly", "2026-09-03", "subscription", "direct_debit", "f4_handoff", None, "2026-08-19", 0, "due"),
    (7, "Home internet", "FibreLink", 7900, "monthly", "2026-08-15", "bill", "bpay", "manual", "2026-07-01", "2026-01-15", 0, "overdue"),
    (8, "Phone plan", "Telco One", 4900, "monthly", "2026-08-31", "bill", "card", "manual", "2026-07-31", "2026-01-31", 0, "paid"),
    (9, "Electricity", "Sparkwell Energy", 14200, "monthly", "2026-09-10", "bill", "bpay", "manual", "2026-08-10", "2026-02-10", 0, "paid"),
    (10, "Opal commute top-up", "Transport card", 3850, "weekly", "2026-08-25", "bill", "card", "manual", "2026-08-11", "2026-03-03", 0, "paid"),
    (11, "Share-house utilities kitty", "Housemates", 2500, "weekly", "2026-08-21", "bill", None, "manual", "2026-08-14", "2026-03-06", 0, "paid"),
    (12, "Cloud storage", "DriveBox", 299, "monthly", "2026-08-28", "subscription", "card", "manual", "2026-03-28", "2026-03-28", 0, "paid"),
]

PAYMENTS = [
    (1, "2026-06-01", 110000),
    (1, "2026-07-01", 110000),
    (1, "2026-08-01", 110000),
    (2, "2026-05-26", 1750),
    (2, "2026-06-09", 1750),
    (2, "2026-06-23", 1750),
    (2, "2026-07-07", 1750),
    (2, "2026-07-21", 1750),
    (2, "2026-08-04", 1750),
    (2, "2026-08-18", 1750),
    (3, "2026-06-16", 1399),
    (3, "2026-07-16", 1399),
    (3, "2026-08-16", 1399),
    (7, "2026-05-15", 7900),
    (7, "2026-06-15", 7900),
    (7, "2026-07-15", 7900),
    (8, "2026-05-31", 4900),
    (8, "2026-06-30", 4900),
    (8, "2026-07-31", 4900),
    (9, "2026-06-10", 12840),
    (9, "2026-07-10", 15120),
    (9, "2026-08-10", 13975),
    (10, "2026-07-14", 3850),
    (10, "2026-07-21", 3850),
    (10, "2026-07-28", 3850),
    (10, "2026-08-04", 3850),
    (10, "2026-08-11", 3850),
    (10, "2026-08-18", 3850),
    (11, "2026-07-10", 2500),
    (11, "2026-07-17", 2500),
    (11, "2026-07-24", 2500),
    (11, "2026-07-31", 2500),
    (11, "2026-08-07", 2500),
    (11, "2026-08-14", 2500),
    (12, "2026-04-28", 299),
    (12, "2026-05-28", 299),
    (12, "2026-06-28", 299),
    (12, "2026-07-28", 299),
]

DISPUTES = [
    (1, 2, "Charged twice on 15 Jul", "draft", "2026-08-15"),
    (2, 6, "Charged after I cancelled", "draft", "2026-08-16"),
    (3, 7, "Amount higher than my plan", "draft", "2026-08-17"),
    (4, 8, "Charged for a month I was on hold", "draft", "2026-08-18"),
    (5, 9, "Estimated bill was way off actual usage", "sent", "2026-08-05"),
    (6, 12, "Charged after I cancelled the trial", "sent", "2026-08-06"),
    (7, 2, "Direct debit taken on a public holiday, no service that week", "sent", "2026-08-07"),
    (8, 7, "Speed downgrade not reflected in price", "resolved", "2026-07-20"),
    (9, 8, "Roaming charge I never authorised", "resolved", "2026-07-22"),
    (10, 9, "Charged twice on 15 Jul", "resolved", "2026-07-25"),
]

CARD_BILLS = {8, 12}
DIRECT_DEBIT_BILLS = {2, 6}

BASE_STEPS = [
    "Check the merchant's billing portal for an itemised statement of the charge.",
    "Contact the merchant's support team and describe the discrepancy in writing.",
]

ESCALATION = ["Merchant support", "Your bank's dispute team", "Australian Financial Complaints Authority (AFCA)"]


def _steps_for_bill(bill_id):
    steps = list(BASE_STEPS)
    if bill_id in DIRECT_DEBIT_BILLS:
        steps.append(
            "Ask the merchant — or your bank — to remove the direct-debit authority. "
            "Cancelling the subscription alone does not stop direct-debit payments."
        )
    elif bill_id in CARD_BILLS:
        steps.append("Cancel the subscription from the app's account page to stop future charges.")
    return steps


def _draft(dispute_id, bill_id, version, letter_text, created_at):
    steps_json = json.dumps({"steps": _steps_for_bill(bill_id), "escalation": ESCALATION})
    return (dispute_id, version, letter_text, steps_json, created_at)


DISPUTE_DRAFTS = [
    _draft(1, 2, 1, "I'm writing to dispute a duplicate charge from Anytime Fitness Ultimo on 15 Jul. My statement shows two identical debits for the same billing period. Please review and refund the duplicate.", "2026-08-15"),
    _draft(1, 2, 2, "Following up on my earlier note: Anytime Fitness Ultimo charged my direct debit twice on 15 Jul for the same fortnightly membership fee. I've attached my bank statement showing both debits and I'm requesting a refund of the duplicate amount.", "2026-08-17"),
    _draft(2, 6, 1, "I cancelled my GymCo membership before this billing cycle, but a charge still appears on my account. Please confirm the cancellation and refund the charge taken after it.", "2026-08-16"),
    _draft(3, 7, 1, "My FibreLink bill this cycle is higher than my plan's advertised rate. Please review the charge against my current plan and adjust or refund the difference.", "2026-08-17"),
    _draft(4, 8, 1, "I was charged by Telco One for a month during which my plan was on hold. Please review the hold dates on my account and refund the charge for that period.", "2026-08-18"),
    _draft(5, 9, 1, "My Sparkwell Energy bill was based on an estimated read that is well above my usual usage. Please arrange an actual meter read and adjust the bill accordingly.", "2026-08-05"),
    _draft(5, 9, 2, "Update on my estimated-bill dispute: I've since submitted a photo of my meter reading to Sparkwell Energy showing usage well below the estimate. Requesting the bill be recalculated on actual usage.", "2026-08-12"),
    _draft(6, 12, 1, "DriveBox charged me after I cancelled during the trial period. Please confirm the cancellation date and refund the charge.", "2026-08-06"),
    _draft(7, 2, 1, "Anytime Fitness Ultimo took a direct debit on a public holiday when the gym was closed for the week. Requesting a pro-rated refund or credit for the closure.", "2026-08-07"),
    _draft(8, 7, 1, "FibreLink downgraded my connection speed without adjusting the price on my plan. Requesting a price adjustment to match the reduced service.", "2026-07-20"),
    _draft(8, 7, 2, "Following up: FibreLink has acknowledged the speed downgrade. Requesting written confirmation of the credit applied to my account.", "2026-07-27"),
    _draft(9, 8, 1, "Telco One billed me for a roaming charge I never authorised while overseas. Requesting the charge be reversed.", "2026-07-22"),
    _draft(10, 9, 1, "I was charged twice by Sparkwell Energy on 15 Jul for the same billing period. Requesting a refund of the duplicate charge.", "2026-07-25"),
]

CHAT_MESSAGES = [
    ("user", "What do my bills add up to?", None, 0, "2026-08-17T09:00:00"),
    ("assistant", "September needs up to $697 beyond rent — your usual weekly and fortnightly bills come to $572–595, plus Netflix starts ($21), GymCo starts ($25), an extra Anytime Fitness payment because three fortnights land in September ($18), and a fifth Opal top-up ($39).", None, 0, "2026-08-17T09:00:05"),
    ("user", "Which subscriptions am I barely using?", None, 0, "2026-08-17T09:02:00"),
    ("assistant", "Cloud storage has billed four times since you last confirmed you're using it — worth a look at $2.99/month.", None, 0, "2026-08-17T09:02:06"),
    ("user", "I cancelled Spotify from September — remove the future payments", None, 0, "2026-08-17T09:05:00"),
    ("assistant", "Got it — I can mark Spotify as ending after 16 Sep, which drops October's estimate by $13.99. Want me to apply that?", '{"op":"update","entity":"bill","id":3,"fields":{"end_date":"2026-09-16"}}', 0, "2026-08-17T09:05:04"),
    ("user", "Draft a note to dispute my GymCo charge", None, 0, "2026-08-17T09:10:00"),
    ("assistant", "I've drafted a dispute letter for GymCo saying you cancelled before this charge, with a three-step checklist including removing the direct-debit authority. You can review and edit it in the Disputes tab.", None, 0, "2026-08-17T09:10:08"),
    ("user", "What's due this week?", None, 0, "2026-08-17T09:15:00"),
    ("assistant", "Coming up this week: Anytime Fitness on 18 Aug ($17.50), Opal top-up on 25 Aug ($38.50), and Prime Video on 24 Aug ($9.99).", None, 0, "2026-08-17T09:15:05"),
]


def seed(connection):
    """Insert the demo dataset if the bills table is empty; safe to call repeatedly."""
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM bills")
    if cursor.fetchone()[0] > 0:
        return
    cursor.executemany(
        """
        INSERT INTO bills
            (id, name, merchant, amount_cents, cadence, next_billing_date, type,
             payment_method, source, confirmed_at, created_at, exclude_from_plan, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        BILLS,
    )
    cursor.executemany(
        "INSERT INTO payments (bill_id, date, amount_cents) VALUES (?, ?, ?)",
        PAYMENTS,
    )
    cursor.executemany(
        "INSERT INTO disputes (id, bill_id, reason, status, opened_at) VALUES (?, ?, ?, ?, ?)",
        DISPUTES,
    )
    cursor.executemany(
        """
        INSERT INTO dispute_drafts (dispute_id, version, letter_text, steps_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        DISPUTE_DRAFTS,
    )
    cursor.executemany(
        """
        INSERT INTO chat_messages (role, content, op_json, applied, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        CHAT_MESSAGES,
    )
    connection.commit()
