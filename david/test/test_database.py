from database.models import Suggestion
from typing import List
from typing import List
from database.models import Feedback
from datetime import datetime
from dateutil import parser
from flask.testing import FlaskClient
from flask import Flask
from database.app import setup_app, db
import pytest
from database.models import Goal

@pytest.fixture()
def app():
    app = setup_app(":memory:")
    app.config.update({"TESTING": True})
    yield app

@pytest.fixture()
def client(app: Flask):
    return app.test_client()

@pytest.fixture()
def app_ctx(app: Flask):
    with app.app_context():
        yield
    
def setup_goals() -> List[Goal]:
    goal1 = Goal()
    goal1.name = "A single dollary doo"
    goal1.cost = 1
    goal1.date = datetime(2026, 8, 25)
    db.session.add(goal1)

    goal2 = Goal()
    goal2.name = "Large Macas Frozen Coke"
    goal2.cost = 1
    goal2.date = datetime(2026, 8, 25)
    db.session.add(goal2)

    db.session.commit()
    return [goal1, goal2]

def setup_feedback() -> List[Feedback]:
    feedback1 = Feedback()
    feedback1.feedback = "I can't do this :("
    db.session.add(feedback1)

    feedback2 = Feedback()
    feedback2.feedback = "This doesn't make sense"
    db.session.add(feedback2)

    db.session.commit()
    return [feedback1, feedback2]
def setup_suggestions() -> List[Suggestion]:
    suggestion1 = Suggestion()
    suggestion1.suggestion = "I can't do this :("
    db.session.add(suggestion1)

    suggestion2 = Suggestion()
    suggestion2.suggestion = "I can't do this :("
    db.session.add(suggestion2)

    db.session.commit()
    return [suggestion1, suggestion2]

@pytest.mark.usefixtures("app_ctx")
def test_get_all_goals(client: FlaskClient):
    expected_goals = setup_goals()
    response = client.get("/goals")
    assert response.status_code == 200
    response_json = response.get_json()
    assert len(response_json) == 2
    assert expected_goals[0].cost == response_json[0]["cost"]
    assert expected_goals[0].name == response_json[0]["name"]
    assert expected_goals[0].date == parser.parse(response_json[0]["date"]).replace(tzinfo=None)

    assert expected_goals[1].cost == response_json[1]["cost"]
    assert expected_goals[1].name == response_json[1]["name"]
    assert expected_goals[1].date == parser.parse(response_json[1]["date"]).replace(tzinfo=None)

@pytest.mark.usefixtures("app_ctx")
def test_get_specific_goals(client: FlaskClient):
    expected_goals = setup_goals()
    response = client.get("/goal/1")
    assert response.status_code == 200
    response_json = response.get_json()
    assert expected_goals[0].cost == response_json["cost"]
    assert expected_goals[0].name == response_json["name"]
    assert expected_goals[0].date == parser.parse(response_json["date"]).replace(tzinfo=None)

@pytest.mark.usefixtures("app_ctx")
def test_get_specific_suggestion(client: FlaskClient):
    expected_feedback = setup_suggestions()
    response = client.get("/feedback/1")
    assert response.status_code == 200
    response_json = response.get_json()
    assert expected_feedback[0].feedback == response_json["feedback"]

@pytest.mark.usefixtures("app_ctx")
def test_get_specific_feedback(client: FlaskClient):
    expected_feedback = setup_feedback()
    response = client.get("/feedback/1")
    assert response.status_code == 200
    response_json = response.get_json()
    assert expected_feedback[0].feedback == response_json["feedback"]
