import os
import threading

from .app import app, setup_database
from .reconcile import reconcile_anomalies


if __name__ == "__main__":
    setup_database(os.environ["DB_PATH"])
    port = int(os.environ["PORT"])

    threading.Thread(target=reconcile_anomalies, daemon=True).start()

    app.run(host="0.0.0.0", port=port)
