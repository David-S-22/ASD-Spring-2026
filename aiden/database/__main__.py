import os

from .app import app, setup_database


if __name__ == "__main__":
    setup_database(os.environ["DB_PATH"])
    port = int(os.environ["PORT"])

    app.run(host="0.0.0.0", port=port)
