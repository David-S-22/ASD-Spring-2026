from flask import Flask
import os

def setup_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def home():
        return "<p>Savings Backend<p>", 200

    @app.route("/goals")
    def get_goals():
        return "", 200

    @app.route("/feedback")
    def get_feedback():
        return "", 200

    @app.route("/suggestions")
    def get_suggestion():
        return "", 200

    return app

if __name__ == "__main__":
    app = setup_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)))

