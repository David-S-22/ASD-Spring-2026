import os
from .app import app, get_env


if __name__ == "__main__":
    port = int(os.environ["PORT"])

    # Frontload env to ensure they're set
    get_env("ANOMALIES_DB_URL")

    app.run(host="0.0.0.0", port=port)
