from datetime import timedelta
from flask import current_app
import html as html_module

from extensions import mail, FLASK_MAIL_AVAILABLE
from models import Task
from utils import utcnow

try:
    from flask_mail import Message as MailMessage
except ImportError:
    MailMessage = None


def _e(value):
    """HTML-эскейп значения (None → пустая строка)."""
    return html_module.escape(str(value)) if value is not None else ''


# ============================================================
#  НАПОМИНАНИЯ О ДЕДЛАЙНАХ
# ============================================================

def send_deadline_email(task, recipient, days_left, role='assignee'):
    """Отправляет напоминание о приближении дедлайна задачи.
    
    role: 'assignee' — исполнителю, 'leader' — руководителю проекта.
    """
    if not FLASK_MAIL_AVAILABLE or mail is None:
        return False
    if not current_app.config.get('MAIL_USERNAME') or not current_app.config.get('MAIL_PASSWORD'):
        return False

    try:
        project = task.project
        leader = project.creator

        if days_left == 0:
            urgency, days_text = "🔴 СЕГОДНЯ", "сегодня"
        elif days_left == 1:
            urgency, days_text = "🟠 ЗАВТРА", "завтра"
        else:
            urgency, days_text = f"🟡 через {days_left} дн.", f"через {days_left} дн."

        safe_title = _e(task.title)
        safe_project_name = _e(project.name)
        safe_recipient_name = _e(recipient.first_name)
        safe_description = _e(task.description or '')
        safe_milestone_name = _e(task.milestone.name) if task.milestone else None
        safe_assignee_name = _e(f"{task.assignee.first_name} {task.assignee.last_name}") if task.assignee else '—'
        safe_leader_name = _e(f"{leader.first_name} {leader.last_name}") if leader else '—'

        if role == 'leader':
            subject = f"⚠️ [Руководителю] Дедлайн {days_text}: {task.title}"
            greeting = f"Здравствуйте, {safe_recipient_name}!"
            intro = (f"Напоминаем как руководителю проекта <strong>«{safe_project_name}»</strong>: "
                     f"{days_text} истекает дедлайн задачи.")
        else:
            subject = f"⚠️ Дедлайн {days_text}: {task.title}"
            greeting = f"Здравствуйте, {safe_recipient_name}!"
            intro = f"Напоминаем: {days_text} истекает дедлайн вашей задачи."

        status_names = {'new': '🆕 Новая', 'in_progress': '🔄 В работе', 'completed': '✅ Завершена'}
        status_display = status_names.get(task.status, task.status)

        html_body = f"""<!DOCTYPE html>
<html><body style="font-family: Arial, sans-serif; background: #f5f7fb; margin: 0; padding: 20px;">
<div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden;">
    <div style="background: linear-gradient(135deg, #4f46e5, #6366f1); padding: 24px; color: white;">
        <h1 style="margin: 0; font-size: 20px;">⚠️ Напоминание о дедлайне</h1>
        <p style="margin: 8px 0 0; opacity: 0.9; font-size: 14px;">Система Workspace</p>
    </div>
    <div style="padding: 24px;">
        <p>{greeting}</p>
        <p>{intro}</p>
        <p style="font-size: 22px; font-weight: bold; color: #dc2626; text-align: center;">{urgency}</p>
        <div style="background: #f8f9fa; border-radius: 8px; padding: 16px; border-left: 4px solid #4f46e5;">
            <h3 style="margin: 0 0 12px; font-size: 16px;">{safe_title}</h3>
            <table style="width: 100%; font-size: 14px;">
                <tr><td style="width: 140px;"><strong>Проект:</strong></td><td>{safe_project_name}</td></tr>
                <tr><td><strong>Дедлайн:</strong></td><td style="color: #dc2626;">{task.due_date.strftime('%d.%m.%Y')}</td></tr>
                <tr><td><strong>Статус:</strong></td><td>{status_display}</td></tr>
                <tr><td><strong>Исполнитель:</strong></td><td>{safe_assignee_name}</td></tr>
                <tr><td><strong>Руководитель:</strong></td><td>{safe_leader_name}</td></tr>
                {f'<tr><td><strong>Веха:</strong></td><td>{safe_milestone_name}</td></tr>' if safe_milestone_name else ''}
            </table>
            {f'<p style="margin: 12px 0 0; font-size: 13px;"><strong>Описание:</strong> {safe_description}</p>' if safe_description else ''}
        </div>
        <div style="text-align: center; margin: 24px 0;">
            <a href="http://84.201.178.247/task/{task.id}" style="background: #4f46e5; color: white; padding: 12px 28px; text-decoration: none; border-radius: 8px;">Открыть задачу</a>
        </div>
    </div>
</div>
</body></html>"""

        msg = MailMessage(subject, recipients=[recipient.email], html=html_body)
        mail.send(msg)
        print(f"✅ Email отправлен на {recipient.email} ({role}) по задаче «{task.title}» ({days_left} дн.)")
        return True

    except Exception as e:
        print(f"❌ Ошибка отправки email на {recipient.email}: {e}")
        return False


def check_and_send_deadline_notifications(days_before=(3, 1, 0)):
    """Отправляет напоминания по всем задачам с дедлайном через 3, 1 или 0 дней."""
    print(f"\n🔍 Проверка дедлайнов: {utcnow().strftime('%Y-%m-%d %H:%M')}")
    now = utcnow()
    sent_count = 0

    max_date = now + timedelta(days=max(days_before) + 1)
    min_date = now - timedelta(days=1)

    tasks = Task.query.filter(
        Task.due_date.isnot(None),
        Task.due_date >= min_date,
        Task.due_date <= max_date,
        Task.status.in_(['new', 'in_progress'])
    ).all()

    for task in tasks:
        days_left = (task.due_date.date() - now.date()).days
        if days_left not in days_before:
            continue

        recipients = []
        if task.assignee and task.assignee.email:
            recipients.append((task.assignee, 'assignee'))

        leader = task.project.creator
        if leader and leader.email:
            if not task.assignee or leader.id != task.assignee.id:
                recipients.append((leader, 'leader'))

        for recipient, role in recipients:
            if send_deadline_email(task, recipient, days_left, role):
                sent_count += 1

    print(f"📧 Отправлено уведомлений: {sent_count}\n")
    return sent_count


# ============================================================
#  ДОСТУП ГОСТЯМ (контакты заказчика / поставщика / субподрядчика)
# ============================================================

def send_guest_credentials(recipient, plain_password, project, inviter):
    """Отправляет контактному лицу (гостю) логин и пароль для входа.
    
    Пароль = email (Вариант A — упрощённый), в письме отдельно
    подчёркивается, что после входа стоит сменить пароль.
    
    Параметры:
        recipient: User-объект гостя
        plain_password: пароль в открытом виде (обычно = email)
        project: Project, в который пригласили
        inviter: User, кто назначил задачу
    """
    if not FLASK_MAIL_AVAILABLE or mail is None:
        print(f"⚠️  Flask-Mail недоступен. Данные для входа: "
              f"{recipient.email} / {plain_password}")
        return False

    if not current_app.config.get('MAIL_USERNAME') or not current_app.config.get('MAIL_PASSWORD'):
        print(f"⚠️  SMTP не настроен. Данные для входа: "
              f"{recipient.email} / {plain_password}")
        return False

    try:
        subject = f"Доступ к проекту «{project.name}»"

        safe_name = _e(f"{recipient.first_name} {recipient.last_name}")
        safe_project = _e(project.name)
        safe_inviter = _e(f"{inviter.first_name} {inviter.last_name}") if inviter else '—'
        safe_email = _e(recipient.email)
        safe_password = _e(plain_password)

        # Ссылка на логин. Если развернёшь домен — поменяй здесь.
        login_url = 'http://84.201.178.247/login'

        html_body = f"""<!DOCTYPE html>
<html><body style="font-family: Arial, sans-serif; background: #f5f7fb; margin: 0; padding: 20px;">
<div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden;">
    <div style="background: linear-gradient(135deg, #4f46e5, #6366f1); padding: 24px; color: white;">
        <h1 style="margin: 0; font-size: 20px;">🔑 Доступ к проекту</h1>
        <p style="margin: 8px 0 0; opacity: 0.9; font-size: 14px;">Система Workspace</p>
    </div>
    <div style="padding: 24px;">
        <p>Здравствуйте, <strong>{safe_name}</strong>!</p>
        <p>Вас пригласили в проект <strong>«{safe_project}»</strong>
           для участия в задачах. Приглашение от: {safe_inviter}.</p>

        <div style="background: #f8f9fa; border-radius: 8px; padding: 16px; margin: 20px 0; border-left: 4px solid #4f46e5;">
            <p style="margin: 0 0 12px; font-size: 14px; color: #666;">Ваши данные для входа:</p>
            <table style="width: 100%; font-size: 14px;">
                <tr>
                    <td style="width: 100px; padding: 6px 0;"><strong>Логин:</strong></td>
                    <td style="padding: 6px 0;">
                        <code style="background: #fff; padding: 2px 6px; border-radius: 3px;">{safe_email}</code>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 6px 0;"><strong>Пароль:</strong></td>
                    <td style="padding: 6px 0;">
                        <code style="background: #fff; padding: 2px 6px; border-radius: 3px;">{safe_password}</code>
                    </td>
                </tr>
            </table>
        </div>

        <div style="background: #fef3c7; border-radius: 8px; padding: 12px 16px; margin: 16px 0; border-left: 4px solid #f59e0b;">
            <p style="margin: 0; font-size: 13px; color: #78350f;">
                ⚠️ <strong>Пароль совпадает с вашим email.</strong>
                Это сделано для удобства первого входа, но небезопасно.
                После входа смените пароль в личном кабинете.
            </p>
        </div>

        <div style="text-align: center; margin: 24px 0;">
            <a href="{login_url}" style="background: #4f46e5; color: white; padding: 12px 28px; text-decoration: none; border-radius: 8px;">Войти в систему</a>
        </div>

        <p style="color: #999; font-size: 12px; margin-top: 24px;">
            После входа вы увидите только задачи, назначенные лично на вас.
            Если письмо попало по ошибке — просто проигнорируйте его.
        </p>
    </div>
</div>
</body></html>"""

        msg = MailMessage(subject, recipients=[recipient.email], html=html_body)
        mail.send(msg)
        print(f"✅ Письмо с доступом отправлено на {recipient.email}")
        return True

    except Exception as e:
        print(f"❌ Ошибка отправки письма для {recipient.email}: {e}")
        # Логируем данные на случай, если админ передаст вручную
        print(f"   ⚠️ Логин: {recipient.email}, пароль: {plain_password}")
        return False