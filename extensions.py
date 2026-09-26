from flask_sqlalchemy import SQLAlchemy

try:
    from flask_mail import Mail
    FLASK_MAIL_AVAILABLE = True
except ImportError:
    Mail = None
    FLASK_MAIL_AVAILABLE = False
    print("⚠️  Flask-Mail не установлен. Email-уведомления недоступны.")

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    HTML = None
    WEASYPRINT_AVAILABLE = False
    print("⚠️  WeasyPrint не установлен. PDF-отчёты недоступны.")

db = SQLAlchemy()
mail = Mail() if FLASK_MAIL_AVAILABLE else None