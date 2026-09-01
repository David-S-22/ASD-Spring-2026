from datetime import datetime
from .models import Goal, Suggestion, Feedback, db

SEED_GOALS = [
    {
        "id": 1,
        "name": "Emergency Fund",
        "cost": 1000,
        "date": datetime(2026, 12, 31),
    },
    {
        "id": 2,
        "name": "Japan Holiday",
        "cost": 3500,
        "date": datetime(2027, 6, 30),
    },
    {
        "id": 3,
        "name": "New Laptop",
        "cost": 1500,
        "date": datetime(2026, 11, 15),
    },
    {
        "id": 4,
        "name": "Car Insurance & Rego",
        "cost": 1200,
        "date": datetime(2026, 10, 31),
    },
    {
        "id": 5,
        "name": "Concert Tickets",
        "cost": 300,
        "date": datetime(2026, 9, 30),
    },
    {
        "id": 6,
        "name": "Home Office Desk Setup",
        "cost": 450,
        "date": datetime(2026, 10, 15),
    },
    {
        "id": 7,
        "name": "Dental Checkup & Clean",
        "cost": 250,
        "date": datetime(2026, 9, 15),
    },
    {
        "id": 8,
        "name": "Christmas Presents",
        "cost": 600,
        "date": datetime(2026, 12, 20),
    },
    {
        "id": 9,
        "name": "Commuter Bicycle",
        "cost": 800,
        "date": datetime(2027, 2, 28),
    },
    {
        "id": 10,
        "name": "Textbooks & Course Materials",
        "cost": 400,
        "date": datetime(2027, 3, 1),
    },
]

SEED_SUGGESTIONS = [
    {
        "id": 1,
        "suggestion": "You can consider reducing your streaming subscriptions by pausing one unused streaming service (like Prime Video) to free up $9.99/month for your Emergency Fund.",
        "accepted": True,
    },
    {
        "id": 2,
        "suggestion": "Cut back on dining out at restaurants to once a week and prepare meals at home to save roughly $80/week towards your Japan Holiday goal.",
        "accepted": True,
    },
    {
        "id": 3,
        "suggestion": "Consider pausing your Anytime Fitness gym membership to save $35/month towards your savings goals.",
        "accepted": False,
    },
    {
        "id": 4,
        "suggestion": "Switch your home internet plan from FibreLink 100Mbps to 50Mbps to save $20/month towards your New Laptop goal.",
        "accepted": False,
    },
    {
        "id": 5,
        "suggestion": "Switch to buying store-brand pantry staples at Woolworths to save approximately $25/week on groceries.",
        "accepted": True,
    },
    {
        "id": 6,
        "suggestion": "Brew coffee at home on weekdays instead of buying daily takeaway coffees to save around $20/week towards your Concert Tickets.",
        "accepted": True,
    },
    {
        "id": 7,
        "suggestion": "Audit your cloud storage subscriptions and cancel duplicate DriveBox tiers to save $2.99/month.",
        "accepted": True,
    },
    {
        "id": 8,
        "suggestion": "Switch electricity providers to Sparkwell Energy's off-peak discount plan to reduce power bills by roughly $30/quarter.",
        "accepted": False,
    },
    {
        "id": 9,
        "suggestion": "Take advantage of off-peak Opal fares on Fridays to save $10/week on your university commute.",
        "accepted": True,
    },
    {
        "id": 10,
        "suggestion": "Pack your own lunch for university or work twice a week instead of buying takeout to save $30/week towards your Car Insurance goal.",
        "accepted": True,
    },
]

SEED_FEEDBACKS = [
    {
        "id": 1,
        "feedback": "I don't want to cancel my Netflix subscription because my family uses it.",
    },
    {
        "id": 2,
        "feedback": "I need to keep my gym membership for health and fitness reasons.",
    },
    {
        "id": 3,
        "feedback": "I want to keep dining out with friends on Friday nights.",
    },
    {
        "id": 4,
        "feedback": "I need high-speed internet for remote software development work.",
    },
    {
        "id": 5,
        "feedback": "Do not suggest cancelling Spotify as I listen to music during study sessions.",
    },
    {
        "id": 6,
        "feedback": "I am happy to cook more at home and buy supermarket house brands.",
    },
    {
        "id": 7,
        "feedback": "I prefer walking or public transport rather than ridesharing services like Uber.",
    },
    {
        "id": 8,
        "feedback": "Keep suggestions focused on recurring subscriptions and dining expenses.",
    },
    {
        "id": 9,
        "feedback": "I cannot change electricity providers because utilities are managed by my landlord.",
    },
    {
        "id": 10,
        "feedback": "I am willing to cut down on daily cafe coffees during the work week.",
    },
]


def seed_database_if_empty():
    """Seed the database tables if they are empty."""
    try:
        has_goals = db.session.execute(db.select(Goal)).scalars().first() is not None
        has_suggestions = db.session.execute(db.select(Suggestion)).scalars().first() is not None
        has_feedbacks = db.session.execute(db.select(Feedback)).scalars().first() is not None

        if not has_goals:
            for item in SEED_GOALS:
                db.session.add(Goal(**item))

        if not has_suggestions:
            for item in SEED_SUGGESTIONS:
                db.session.add(Suggestion(**item))

        if not has_feedbacks:
            for item in SEED_FEEDBACKS:
                db.session.add(Feedback(**item))

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def seed_database():
    """Seed the database if empty."""
    seed_database_if_empty()
