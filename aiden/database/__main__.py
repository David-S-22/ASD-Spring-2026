import os
from .app import app, setup


if __name__ == "__main__":
    setup(os.environ["DB_PATH"])
    port = int(os.environ["PORT"])

    app.run(host="0.0.0.0", port=port)
