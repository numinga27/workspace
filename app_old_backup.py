from flask import Flask
from datetime import datetime, timezone

from config import Config
from extensions import db, mail, FLASK_MAIL_AVAILABLE
from models import User
from blueprints import register_blueprints


# ============================================================
#  ХЕЛПЕРЫ ДЛЯ CONTEXT PROCESSORS
# ============================================================

def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- Инициализация расширений ---
    db.init_app(app)
    if FLASK_MAIL_AVAILABLE and mail is not None:
        mail.init_app(app)

    # --- Регистрация Blueprints ---
    register_blueprints(app)

    # --- Context Processors (непрочитанные + просроченные) ---
    @app.context_processor
    def inject_unread_counts():
        from flask import session
        from utils import get_unread_counts
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user:
                return {'unread_counts': get_unread_counts(user)}
        return {'unread_counts': {}}

    @app.context_processor
    def inject_overdue_count():
        from flask import session
        from models import Task
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user:
                overdue_count = Task.query.filter_by(assigned_to=user.id)\
                    .filter(Task.status != 'completed')\
                    .filter(Task.due_date < _utcnow()).count()
                return {'my_overdue_count': overdue_count}
        return {'my_overdue_count': 0}

    # --- Создание таблиц и seed админа ---
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                first_name='Иван',
                last_name='Петров',
                company='ООО Рога и Копыта',
                email='admin@example.com',
                role='admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Создан администратор: admin@example.com / admin123")

    return app


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5001)