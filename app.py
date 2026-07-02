"""Entrypoint for the Mealie planner web app.

Serves via `python app.py` for local development; production uses gunicorn
(see Dockerfile) pointing at the same `app` object.
"""
from mealie_planner.web import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9926, debug=False)
