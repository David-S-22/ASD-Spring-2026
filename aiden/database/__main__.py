from .config import config
from .app import app, setup_database


if __name__ == "__main__":
    config.check_all()

    setup_database(config.DB_PATH)

    app.run(host="0.0.0.0", port=config.PORT)
