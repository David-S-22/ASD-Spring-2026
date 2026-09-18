from .app import app, setup_database
from .config import config
from .reconcile import start_reconcile


if __name__ == "__main__":
    config.check_all()

    setup_database(config.DB_PATH)
    start_reconcile(app)

    app.run(host="0.0.0.0", port=config.PORT)
