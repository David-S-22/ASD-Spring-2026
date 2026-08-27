from flask import jsonify
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
from dataclasses import asdict
from json import dumps

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
def test_get_all_feedbacks(client: FlaskClient):
    expected_feedback = setup_feedback()
    response = client.get("/feedbacks")
    assert response.status_code == 200
    response_json = response.get_json()
    assert len(response_json) == 2
    assert expected_feedback[0].feedback == response_json[0]["feedback"]
   
    assert expected_feedback[1].feedback == response_json[1]["feedback"]
  
@pytest.mark.usefixtures("app_ctx")
def test_get_all_suggestions(client: FlaskClient):
    expected_suggestions = setup_suggestions()
    response = client.get("/suggestions")
    assert response.status_code == 200
    response_json = response.get_json()
    assert len(response_json) == 2
    assert expected_suggestions[0].suggestion == response_json[0]["suggestion"]

    assert expected_suggestions[1].suggestion == response_json[1]["suggestion"]

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
    expected_suggestion = setup_suggestions()
    response = client.get("/suggestion/1")
    assert response.status_code == 200
    response_json = response.get_json()
    assert expected_suggestion[0].suggestion == response_json["suggestion"]

@pytest.mark.usefixtures("app_ctx")
def test_get_specific_feedback(client: FlaskClient):
    expected_feedback = setup_feedback()
    response = client.get("/feedback/1")
    assert response.status_code == 200
    response_json = response.get_json()
    assert expected_feedback[0].feedback == response_json["feedback"]


@pytest.mark.usefixtures("app_ctx")
def test_delete_goal(client: FlaskClient):
    goals = setup_goals()
    response = client.delete(f"/goal/{goals[0].id}")
    assert response.status_code == 204
    remaining_goals = db.session.execute(db.select(Goal)).scalars().all()
    assert len(remaining_goals) == 1
    assert remaining_goals[0].id == goals[1].id

@pytest.mark.usefixtures("app_ctx")
def test_update_goal(client: FlaskClient):
    goals = setup_goals()
    new_name = "two schmickles"
    goals[0].name = new_name
    new_cost = 2
    goals[0].cost = new_cost
    new_date = datetime(2025, 6, 7);
    goals[0].date = new_date
    updated_goal_json = dumps(asdict(goals[0]), default=str)
    response = client.patch(f"/goal/{goals[0].id}", data=updated_goal_json, content_type="application/json")
    assert response.status_code == 200

    updated_goal = db.session.execute(db.select(Goal).where(Goal.id == goals[0].id)).scalar_one()
    assert updated_goal.name == new_name
    assert updated_goal.cost == new_cost
    assert updated_goal.date == new_date

@pytest.mark.usefixtures("app_ctx")
def test_update_goal_partial_update(client: FlaskClient):
    goals = setup_goals()
    new_cost = 5
    goals[1].cost = new_cost
    updated_goal_json = dumps(asdict(goals[1]), default=str)
    response = client.patch(f"/goal/{goals[1].id}", data=updated_goal_json, content_type="application/json")
    assert response.status_code == 200

    updated_goal = db.session.execute(db.select(Goal).where(Goal.id == goals[1].id)).scalar_one()
    assert updated_goal.cost == new_cost
    assert updated_goal.name == goals[1].name
    assert updated_goal.date == goals[1].date

@pytest.mark.usefixtures("app_ctx")
def test_update_goal_rejects_invalid_messages(client: FlaskClient):
    goals = setup_goals()
    response = client.patch(f"/goal/{goals[0].id}", data="", content_type="application/json")
    assert response.status_code == 400

@pytest.mark.usefixtures("app_ctx")
def test_create_goal(client: FlaskClient):
    goal_to_create = Goal()
    goal_to_create.cost = 5
    goal_to_create.name = "Borgr"
    goal_to_create.date = datetime(2022, 12, 31)
    updated_goal_json = dumps(asdict(goal_to_create), default=str)
    response = client.post("/goal", content_type="application/json", data=updated_goal_json)
    assert response.status_code == 201

    new_goal = db.session.execute(db.select(Goal)).scalar_one()
    assert new_goal.name == goal_to_create.name
    assert new_goal.cost == goal_to_create.cost
    assert new_goal.date == goal_to_create.date
