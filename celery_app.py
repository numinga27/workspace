# celery_app.py
from app import create_app
from extensions import celery

# Создаем Flask-приложение, чтобы Celery мог использовать его контекст (БД, конфиг)
flask_app = create_app()

# Это объект, который будет искать Celery
celery_app = flask_app.extensions["celery"]