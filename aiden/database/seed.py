from typing import Iterable

from sqlalchemy import select

from .models import Anomaly, db


SEED_ANOMALIES = (
    (1, "A second identical rent payment was recorded on the same day.", True),
    (2, "A recurring Netflix subscription charge was incorrectly flagged.", False),
    (4, "The transport card top-up is consistent with the user's usual travel spending.", False),
    (5, "A duplicate rent payment appears on the same day as another rent charge.", True),
    (6, "The rent payment matches the user's regular housing expense.", False),
    (7, "The fitness membership charge matches the user's established routine.", False),
    (9, "The Prime Video subscription is a routine recurring charge.", False),
    (13, "A shared household transfer may be an unusual payment to another account.", None),
    (20, "The shared household transfer matches the user's earlier transfer.", False),
    (22, "Spotify was charged again one week after the previous subscription payment.", True),
    (24, "A second identical electricity charge appeared one week after the previous bill.", True),
    (26, "Spotify's subscription charge increased from its usual amount.", None),
    (27, "A restaurant purchase is higher than the user's usual dining transactions.", None),
    (28, "Another restaurant purchase followed within a week of a high-value dinner.", None),
    (29, "A further high-value dinner at the same restaurant occurred two weeks later.", None),
    (31, "A second restaurant purchase appeared within a fortnight.", False),
    (34, "The charge is from an unrecognised merchant and has no clear description.", True),
)


def seed_database_if_empty(transaction_ids: Iterable[int]) -> int:
    """Add missing demo anomalies for existing transactions; return rows added."""

    try:
        available_transaction_ids = set(transaction_ids)
        existing_transaction_ids = set(
            db.session.scalars(select(Anomaly.transaction_id)).all()
        )
        seeded = [
            Anomaly(
                transaction_id=transaction_id,
                agent_reason_suspected=reason,
                is_confirmed_by_user=is_confirmed,
            )
            for transaction_id, reason, is_confirmed in SEED_ANOMALIES
            if transaction_id in available_transaction_ids
            and transaction_id not in existing_transaction_ids
        ]
        db.session.add_all(seeded)
        db.session.commit()
        return len(seeded)
    except Exception:
        db.session.rollback()
        raise
