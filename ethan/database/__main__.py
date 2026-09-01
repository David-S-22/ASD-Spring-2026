import os

from .app import create_app


if __name__ == "__main__":
    seed_demo_data = os.environ.get("SEED_DEMO_DATA", "1") != "0"
    app = create_app(os.environ["DB_PATH"], seed_demo_data=seed_demo_data)
    port = int(os.environ["PORT"])
    app.run(host="0.0.0.0", port=port)
