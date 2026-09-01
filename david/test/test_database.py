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
    suggestion1.accepted = True
    db.session.add(suggestion1)

    suggestion2 = Suggestion()
    suggestion2.suggestion = "I can't do this :("
    suggestion2.accepted = False
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
    assert expected_suggestions[0].accepted == response_json[0]["accepted"]

    assert expected_suggestions[1].suggestion == response_json[1]["suggestion"]
    assert expected_suggestions[1].accepted == response_json[1]["accepted"]

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
    assert expected_suggestion[0].accepted == response_json["accepted"]

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
def test_delete_suggestion(client: FlaskClient):
    suggestions = setup_suggestions()
    response = client.delete(f"/suggestion/{suggestions[0].id}")
    assert response.status_code == 204
    remaining_suggestions = db.session.execute(db.select(Suggestion)).scalars().all()
    assert len(remaining_suggestions) == 1
    assert remaining_suggestions[0].id == suggestions[1].id

@pytest.mark.usefixtures("app_ctx")
def test_delete_feedback(client: FlaskClient):
    feedbacks = setup_feedback()
    response = client.delete(f"/feedback/{feedbacks[0].id}")
    assert response.status_code == 204
    remaining_feedbacks = db.session.execute(db.select(Feedback)).scalars().all()
    assert len(remaining_feedbacks) == 1
    assert remaining_feedbacks[0].id == feedbacks[1].id

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
    headers = {"Content-type": "application/json"}
    response = client.patch(f"/goal/{goals[0].id}", data=updated_goal_json, content_type="application/json")
    assert response.status_code == 200

    updated_goal = db.session.execute(db.select(Goal).where(Goal.id == goals[0].id)).scalar_one()
    assert updated_goal.name == new_name
    assert updated_goal.cost == new_cost
    assert updated_goal.date == new_date

@pytest.mark.usefixtures("app_ctx")
def test_update_suggestion(client: FlaskClient):
    suggestions = setup_suggestions()
    new_suggestion = "two schmickles"
    suggestions[0].suggestion = new_suggestion
    suggestions[0].accepted = False
    updated_suggestion_json = dumps(asdict(suggestions[0]), default=str)
    response = client.patch(f"/suggestion/{suggestions[0].id}", data=updated_suggestion_json, content_type="application/json")
    assert response.status_code == 200

    updated_suggestion = db.session.execute(db.select(Suggestion).where(Suggestion.id == suggestions[0].id)).scalar_one()
    assert updated_suggestion.suggestion == new_suggestion
    assert updated_suggestion.accepted is False

@pytest.mark.usefixtures("app_ctx")
def test_update_suggestion_partial_update(client: FlaskClient):
    suggestions = setup_suggestions()
    response = client.patch(f"/suggestion/{suggestions[0].id}", json={"accepted": False})
    assert response.status_code == 200

    updated_suggestion = db.session.execute(db.select(Suggestion).where(Suggestion.id == suggestions[0].id)).scalar_one()
    assert updated_suggestion.accepted is False
    assert updated_suggestion.suggestion == suggestions[0].suggestion

@pytest.mark.usefixtures("app_ctx")
def test_update_feedback(client: FlaskClient):
    feedbacks = setup_feedback()
    new_feedback = "two schmickles"
    feedbacks[0].feedback = new_feedback
    updated_feedback_json = dumps(asdict(feedbacks[0]), default=str)
    response = client.patch(f"/feedback/{feedbacks[0].id}", data=updated_feedback_json, content_type="application/json")
    assert response.status_code == 200

    updated_feedback = db.session.execute(db.select(Feedback).where(Feedback.id == feedbacks[0].id)).scalar_one()
    assert updated_feedback.feedback == new_feedback

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
def test_update_suggestion_rejects_invalid_messages(client: FlaskClient):
    suggestions = setup_suggestions()
    response = client.patch(f"/suggestion/{suggestions[0].id}", data="", content_type="application/json")
    assert response.status_code == 400

@pytest.mark.usefixtures("app_ctx")
def test_update_feedback_rejects_invalid_messages(client: FlaskClient):
    feedbacks = setup_feedback()
    response = client.patch(f"/feedback/{feedbacks[0].id}", data="", content_type="application/json")
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

@pytest.mark.usefixtures("app_ctx")
def test_create_suggestion(client: FlaskClient):
    suggestion_to_create = Suggestion()
    suggestion_to_create.suggestion = "Borgr"
    suggestion_to_create.accepted = True
    updated_suggestion_json = dumps(asdict(suggestion_to_create), default=str)
    response = client.post("/suggestion", content_type="application/json", data=updated_suggestion_json)
    assert response.status_code == 201

    new_suggestion = db.session.execute(db.select(Suggestion)).scalar_one()
    assert new_suggestion.suggestion == suggestion_to_create.suggestion
    assert new_suggestion.accepted == suggestion_to_create.accepted

@pytest.mark.usefixtures("app_ctx")
def test_create_suggestion_missing_accepted(client: FlaskClient):
    response = client.post("/suggestion", content_type="application/json", data=dumps({"suggestion": "Borgr"}))
    assert response.status_code == 400

@pytest.mark.usefixtures("app_ctx")
def test_create_feedback(client: FlaskClient):
    feedback_to_create = Feedback()
    feedback_to_create.feedback = "Borgr"
    updated_feedback_json = dumps(asdict(feedback_to_create), default=str)
    response = client.post("/feedback", content_type="application/json", data=updated_feedback_json)
    assert response.status_code == 201

    new_feedback = db.session.execute(db.select(Feedback)).scalar_one()
    assert new_feedback.feedback == feedback_to_create.feedback

def test_goal_to_dto():
    now = datetime(2026, 8, 25)
    goal = Goal(id=1, name="Goal 1", cost=100, date=now)
    dto_obj = goal.to_dto()
    assert dto_obj.id == 1
    assert dto_obj.name == "Goal 1"
    assert dto_obj.cost == 100
    assert dto_obj.date == now
    assert goal.to_dto() == dto_obj

def test_suggestion_to_dto():
    suggestion = Suggestion(id=2, suggestion="A suggestion", accepted=True)
    dto_obj = suggestion.to_dto()
    assert dto_obj.id == 2
    assert dto_obj.suggestion == "A suggestion"
    assert dto_obj.accepted is True
    assert suggestion.to_dto() == dto_obj

def test_feedback_to_dto():
    feedback = Feedback(id=3, feedback="A feedback")
    dto_obj = feedback.to_dto()
    assert dto_obj.id == 3
    assert dto_obj.feedback == "A feedback"
    assert feedback.to_dto() == dto_obj

def test_try_parse_bool():
    from database.helpers import try_parse_bool
    assert try_parse_bool(True) is True
    assert try_parse_bool(False) is False
    assert try_parse_bool("True") is True
    assert try_parse_bool("true") is True
    assert try_parse_bool("False") is False
    assert try_parse_bool("false") is False
    assert try_parse_bool("invalid") is None
    assert try_parse_bool(123) is None
    assert try_parse_bool(None) is None


def test_seed_database_if_empty():
    from database.seed import seed_database_if_empty, SEED_GOALS, SEED_SUGGESTIONS, SEED_FEEDBACKS
    test_app = setup_app(":memory:")
    with test_app.app_context():
        assert len(db.session.execute(db.select(Goal)).scalars().all()) == 0

        # Run seeding
        seed_database_if_empty()

        goals = db.session.execute(db.select(Goal)).scalars().all()
        suggestions = db.session.execute(db.select(Suggestion)).scalars().all()
        feedbacks = db.session.execute(db.select(Feedback)).scalars().all()

        assert len(goals) == len(SEED_GOALS)
        assert len(suggestions) == len(SEED_SUGGESTIONS)
        assert len(feedbacks) == len(SEED_FEEDBACKS)

        seed_database_if_empty()
        assert len(db.session.execute(db.select(Goal)).scalars().all()) == len(SEED_GOALS)
        assert len(db.session.execute(db.select(Suggestion)).scalars().all()) == len(SEED_SUGGESTIONS)
        assert len(db.session.execute(db.select(Feedback)).scalars().all()) == len(SEED_FEEDBACKS)



