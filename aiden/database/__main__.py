import threading

from .app import app, setup_database
from .config import config
from .reconcile import reconcile_anomalies


if __name__ == "__main__":
    config.check_all()

    setup_database(config.DB_PATH)

    threading.Thread(target=reconcile_anomalies, daemon=True).start()

    app.run(host="0.0.0.0", port=config.PORT)
