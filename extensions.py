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