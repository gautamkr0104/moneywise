"""Development entry point.

Usage:
    python run.py            # runs the Flask dev server on http://127.0.0.1:5000
    flask --app run.py run   # equivalent, via the Flask CLI
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Debug mode is controlled by config (FLASK_ENV / FLASK_DEBUG), not here.
    app.run(host="127.0.0.1", port=5000, debug=app.debug)
