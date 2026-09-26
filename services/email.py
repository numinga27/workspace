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
    return html_module.escape(str(value)) if value is not None else ''


def send_deadline_email(task, recipient, days_left, role='assignee'):
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