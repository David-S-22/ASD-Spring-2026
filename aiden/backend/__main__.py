import logging
import os

from .config import config
from .app import app
from .services import ollama_api


if __name__ == "__main__":
    config.check_all()

    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel("INFO")
    app.logger.propagate = False
    ollama_api.logger.setLevel(
        os.environ.get("OLLAMA_LOG_LEVEL", "INFO").upper()
    )
    app.run(host="0.0.0.0", port=config.PORT)
