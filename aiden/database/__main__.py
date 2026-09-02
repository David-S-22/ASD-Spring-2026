from .app import app, setup_database
from .config import DB_PATH, PORT


if __name__ == "__main__":
    setup_database(DB_PATH)

    app.run(host="0.0.0.0", port=PORT)
