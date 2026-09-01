from datetime import datetime
from typing import List
from .models import Goal, Suggestion, Feedback, db


def get_goals() -> List[Goal]:
    return [
        Goal(id=1, name="Emergency Fund", cost=1000, date=datetime(2026, 12, 31)),
        Goal(id=2, name="Japan Holiday", cost=3500, date=datetime(2027, 6, 30)),
        Goal(id=3, name="New Laptop", cost=1500, date=datetime(2026, 11, 15)),
        Goal(id=4, name="Car Insurance & Rego", cost=1200, date=datetime(2026, 10, 31)),
        Goal(id=5, name="Concert Tickets", cost=300, date=datetime(2026, 9, 30)),
        Goal(id=6, name="Home Office Desk Setup", cost=450, date=datetime(2026, 10, 15)),
        Goal(id=7, name="Dental Checkup & Clean", cost=250, date=datetime(2026, 9, 15)),
        Goal(id=8, name="Christmas Presents", cost=600, date=datetime(2026, 12, 20)),
        Goal(id=9, name="Commuter Bicycle", cost=800, date=datetime(2027, 2, 28)),
        Goal(id=10, name="Textbooks & Course Materials", cost=400, date=datetime(2027, 3, 1)),
    ]


def get_suggestions() -> List[Suggestion]:
    return [
        Suggestion(id=1, suggestion="You can consider reducing your streaming subscriptions by pausing one unused streaming service (like Prime Video) to free up $9.99/month for your Emergency Fund.", accepted=True),
        Suggestion(id=2, suggestion="Cut back on dining out at restaurants to once a week and prepare meals at home to save roughly $80/week towards your Japan Holiday goal.", accepted=True),
        Suggestion(id=3, suggestion="Consider pausing your Anytime Fitness gym membership to save $35/month towards your savings goals.", accepted=False),
        Suggestion(id=4, suggestion="Switch your home internet plan from FibreLink 100Mbps to 50Mbps to save $20/month towards your New Laptop goal.", accepted=False),
        Suggestion(id=5, suggestion="Switch to buying store-brand pantry staples at Woolworths to save approximately $25/week on groceries.", accepted=True),
        Suggestion(id=6, suggestion="Brew coffee at home on weekdays instead of buying daily takeaway coffees to save around $20/week towards your Concert Tickets.", accepted=True),
        Suggestion(id=7, suggestion="Audit your cloud storage subscriptions and cancel duplicate DriveBox tiers to save $2.99/month.", accepted=True),
        Suggestion(id=8, suggestion="Switch electricity providers to Sparkwell Energy's off-peak discount plan to reduce power bills by roughly $30/quarter.", accepted=False),
        Suggestion(id=9, suggestion="Take advantage of off-peak Opal fares on Fridays to save $10/week on your university commute.", accepted=True),
        Suggestion(id=10, suggestion="Pack your own lunch for university or work twice a week instead of buying takeout to save $30/week towards your Car Insurance goal.", accepted=True),
    ]


def get_feedbacks() -> List[Feedback]:
    return [
        Feedback(id=1, feedback="I don't want to cancel my Netflix subscription because my family uses it."),
        Feedback(id=2, feedback="I need to keep my gym membership for health and fitness reasons."),
        Feedback(id=3, feedback="I want to keep dining out with friends on Friday nights."),
        Feedback(id=4, feedback="I need high-speed internet for remote software development work."),
        Feedback(id=5, feedback="Do not suggest cancelling Spotify as I listen to music during study sessions."),
        Feedback(id=6, feedback="I am happy to cook more at home and buy supermarket house brands."),
        Feedback(id=7, feedback="I prefer walking or public transport rather than ridesharing services like Uber."),
        Feedback(id=8, feedback="Keep suggestions focused on recurring subscriptions and dining expenses."),
        Feedback(id=9, feedback="I cannot change electricity providers because utilities are managed by my landlord."),
        Feedback(id=10, feedback="I am willing to cut down on daily cafe coffees during the work week."),
    ]


goals = get_goals()
suggestions = get_suggestions()
feedbacks = get_feedbacks()


def seed_database_if_empty():
    """Seed the database tables using add_all if they are empty."""
    try:
        has_goals = db.session.execute(db.select(Goal)).scalars().first() is not None
        has_suggestions = db.session.execute(db.select(Suggestion)).scalars().first() is not None
        has_feedbacks = db.session.execute(db.select(Feedback)).scalars().first() is not None

        if not has_goals:
            db.session.add_all(goals)

        if not has_suggestions:
            db.session.add_all(suggestions)

        if not has_feedbacks:
            db.session.add_all(feedbacks)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def seed_database():
    """Seed the database if empty."""
    seed_database_if_empty()
