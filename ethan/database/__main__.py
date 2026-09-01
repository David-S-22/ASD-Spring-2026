import os

from .app import create_app


if __name__ == "__main__":
    app = create_app(os.environ["DB_PATH"])
    port = int(os.environ["PORT"])
    app.run(host="0.0.0.0", port=port)
