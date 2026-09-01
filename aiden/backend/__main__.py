from .app import app
from .helpers import get_env


if __name__ == "__main__":
    port = int(get_env("PORT"))

    # Frontload env to ensure they're set
    get_env("ANOMALIES_DB_URL")
    get_env("OLLAMA_URL")
    get_env("OLLAMA_MODEL")

    app.logger.setLevel("INFO")
    app.run(host="0.0.0.0", port=port)
