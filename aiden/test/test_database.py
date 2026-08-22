from database.app import app


def test_index():
    with app.test_client() as client:
        index = client.get("/")

        assert index.status_code == 200
        assert index.text == "hello this is the index"
