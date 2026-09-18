from .config import config
from .app import app


if __name__ == "__main__":
    config.check_all()

    app.logger.setLevel("INFO")
    app.run(host="0.0.0.0", port=config.PORT)
