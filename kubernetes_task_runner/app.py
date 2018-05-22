""" REST API for Kubernetes Task Runner """
from flask import Flask


def create_app(config=None):
    from .views import api_views
    from .models import db
    from .tasks import celery

    app = Flask(__name__)

    app.config.from_mapping(config or {})

    celery.conf.update(app.config)

    # initialize flask-mongoengine
    db.init_app(app)

    # register views
    app.register_blueprint(api_views)

    return app
