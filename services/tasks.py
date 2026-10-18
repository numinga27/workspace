"""Фоновые задачи Celery для отправки Push-уведомлений и Email.

ВНИМАНИЕ: Используем @shared_task вместо @celery.task, чтобы задачи
не привязывались к пустому объекту Celery на момент импорта.
shared_task регистрируется в текущем (default) Celery-приложении,
которое настраивается через celery_init_app(app) в app.py.
"""
from celery import shared_task


# ============================================================
#  PUSH-УВЕДОМЛЕНИЯ
# ============================================================

@shared_task(name='send_push_async')
def send_push_async(user_id, title, body, url=None, tag=None, icon=None):
    """Фоновая отправка Push-уведомления.
    
    Параметры:
        user_id: ID получателя
        title:   заголовок уведомления
        body:    текст
        url:     куда открыть при клике
        tag:     уникальный тег (одинаковые теги заменяют друг друга)
        icon:    путь к иконке
    """
    from services.push import send_push_to_user
    return send_push_to_user(user_id, title, body, url, tag, icon)


# ============================================================
#  EMAIL-УВЕДОМЛЕНИЯ
# ============================================================

@shared_task(name='send_email_async')
def send_email_async(recipient_email, subject, html_body):
    """Фоновая отправка Email.
    
    Параметры:
        recipient_email: email получателя
        subject:         тема письма
        html_body:       HTML-содержимое письма
    """
    from flask_mail import Message as MailMessage
    from extensions import mail, FLASK_MAIL_AVAILABLE
    
    if not FLASK_MAIL_AVAILABLE or mail is None:
        print("⚠️ Flask-Mail не доступен, письмо не отправлено")
        return False
    
    try:
        msg = MailMessage(subject, recipients=[recipient_email], html=html_body)
        mail.send(msg)
        print(f"✅ Email отправлен на {recipient_email} (фон)")
        return True
    except Exception as e:
        print(f"❌ Ошибка фоновой отправки email на {recipient_email}: {e}")
        return False