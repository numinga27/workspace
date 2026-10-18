from flask_sqlalchemy import SQLAlchemy

# ============================================================
#  КЭШИРОВАНИЕ (Flask-Caching)
# ============================================================
try:
    from flask_caching import Cache
    cache = Cache()
except ImportError:
    cache = None
    print("⚠️  Flask-Caching не установлен. Кэширование отключено.")


# ============================================================
#  CELERY (фоновая очередь задач)
# ============================================================
try:
    from celery import Celery, Task

    # ← Глобальный объект Celery (один на всё приложение).
    # Задачи в services/tasks.py декорируются через @celery.task,
    # поэтому они должны использовать именно этот объект.
    celery = Celery()

    def celery_init_app(app):
        """Настраивает глобальный объект celery под Flask-приложение."""
        class FlaskTask(Task):
            def __call__(self, *args, **kwargs):
                # ← Задача выполняется в контексте Flask (доступ к db, config)
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.task_cls = FlaskTask
        celery.config_from_object(app.config["CELERY"])
        celery.set_default()
        app.extensions["celery"] = celery
        return celery

except ImportError:
    celery = None

    def celery_init_app(app):
        print("⚠️  Celery не установлен. Фоновые задачи отключены.")
        return None


# ============================================================
#  ПОЧТА (Flask-Mail)
# ============================================================
try:
    from flask_mail import Mail
    FLASK_MAIL_AVAILABLE = True
except ImportError:
    Mail = None
    FLASK_MAIL_AVAILABLE = False
    print("⚠️  Flask-Mail не установлен. Email-уведомления недоступны.")


# ============================================================
#  PDF (WeasyPrint)
# ============================================================
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    HTML = None
    WEASYPRINT_AVAILABLE = False
    print("⚠️  WeasyPrint не установлен. PDF-отчёты недоступны.")


# ============================================================
#  ИНИЦИАЛИЗАЦИЯ РАСШИРЕНИЙ
# ============================================================
db = SQLAlchemy()
mail = Mail() if FLASK_MAIL_AVAILABLE else None