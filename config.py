import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-change-me-in-production')

    # ============================================================
    #  БАЗА ДАННЫХ
    #  Приоритет у DATABASE_URL из окружения (PostgreSQL на сервере).
    #  Если переменной нет — локально используется SQLite (workspace.db),
    #  чтобы не ставить PostgreSQL на Mac для разработки.
    # ============================================================
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL:
        # SQLAlchemy 2.x не понимает postgres://, только postgresql://
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'workspace.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ============================================================
    #  ЗАГРУЗКА ФАЙЛОВ
    # ============================================================
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # ============================================================
    #  СЕССИИ
    # ============================================================
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # ============================================================
    #  ПОЧТА
    # ============================================================
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.yandex.ru')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 465))
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'true').lower() == 'true'
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME', '')