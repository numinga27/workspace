"""Сервис web-push уведомлений (PWA).

Использует pywebpush для отправки пушей через Apple Push Service / Mozilla.
"""
import json
import os
from datetime import datetime, timezone

from flask import current_app

from extensions import db
from models import PushSubscription


def _utcnow():
    return datetime.now(timezone.utc)


def _is_configured():
    """Проверяет, что VAPID-ключи и файл есть."""
    return bool(
        current_app.config.get('VAPID_PUBLIC_KEY')
        and current_app.config.get('VAPID_PRIVATE_KEY_PATH')
        and os.path.exists(current_app.config['VAPID_PRIVATE_KEY_PATH'])
    )


def send_push_to_user(user_id, title, body, url=None, tag=None, icon=None):
    """Отправить push-уведомление всем активным подпискам пользователя.

    Параметры:
        user_id: ID получателя
        title:   заголовок уведомления
        body:    текст
        url:     куда открыть при клике
        tag:     уникальный тег (одинаковые теги заменяют друг друга)
        icon:    путь к иконке
    """
    if not _is_configured():
        print('⚠️ Web Push не настроен (VAPID ключи отсутствуют)')
        return 0

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print('⚠️ pywebpush не установлен')
        return 0

    subs = PushSubscription.query.filter_by(user_id=user_id, is_active=True).all()
    if not subs:
        print(f'ℹ️ Нет активных подписок для user #{user_id}')
        return 0

    payload = {
        'title': title,
        'body': body,
        'url': url or '/',
        'tag': tag,
        'icon': icon or '/static/icons/icon-192.png',
        'badge': '/static/icons/icon-192.png',
        'data': {
            'url': url or '/',
            'ts': int(_utcnow().timestamp()),
        }
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    sent = 0
    removed = 0

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {
                        'p256dh': sub.p256dh,
                        'auth': sub.auth,
                    }
                },
                data=payload_json,
                vapid_private_key=current_app.config['VAPID_PRIVATE_KEY_PATH'],
                vapid_claims={
                    'sub': current_app.config.get(
                        'VAPID_CLAIM_EMAIL',
                        'mailto:admin@example.com'
                    )
                },
                timeout=10,
            )
            sub.last_used_at = _utcnow()
            sent += 1

        except WebPushException as e:
            status = getattr(e.response, 'status_code', None)

            if status in (404, 410):
                sub.is_active = False
                removed += 1
                print(f'🗑️ Подписка #{sub.id} удалена (status={status})')
            else:
                print(f'❌ Ошибка отправки (sub #{sub.id}): {e}')

        except Exception as e:
            print(f'❌ Неожиданная ошибка (sub #{sub.id}): {e}')

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    if sent or removed:
        print(f'📤 Push → user #{user_id}: отправлено {sent}, удалено {removed}')

    return sent


# ============================================================
#  ХЕЛПЕРЫ ДЛЯ КОНКРЕТНЫХ СОБЫТИЙ
# ============================================================

def notify_new_task(task, poster):
    """Push: назначена новая задача."""
    if not task.assigned_to:
        return 0

    from models import User
    assignee = User.query.get(task.assigned_to)
    if not assignee:
        return 0

    if poster and assignee.id == poster.id:
        return 0

    project_name = task.project.name if task.project else '—'
    due_text = (
        f'Дедлайн: {task.due_date.strftime("%d.%m.%Y")}'
        if task.due_date else 'Без дедлайна'
    )

    return send_push_to_user(
        user_id=assignee.id,
        title='📋 Новая задача',
        body=f'{task.title}\n{project_name} · {due_text}',
        url=f'/task/{task.id}',
        tag=f'task-{task.id}',
    )


def notify_new_subtask(subtask, poster):
    """Push: назначена новая подзадача."""
    if not subtask.assigned_to:
        return 0

    from models import User
    assignee = User.query.get(subtask.assigned_to)
    if not assignee:
        return 0

    if poster and assignee.id == poster.id:
        return 0

    project_name = subtask.project.name if subtask.project else '—'
    parent_title = subtask.parent_task.title if subtask.parent_task else ''

    return send_push_to_user(
        user_id=assignee.id,
        title='📋 Новая подзадача',
        body=f'{subtask.title}\nВ задаче: {parent_title} · {project_name}',
        url=f'/task/{subtask.id}',
        tag=f'subtask-{subtask.id}',
    )


def notify_new_message(message, mentioned_user_ids=None):
    """Push: новое сообщение в чате проекта."""
    if not message.project:
        return 0

    from models import ProjectMember

    members = ProjectMember.query.filter_by(project_id=message.project_id).all()

    author = message.author
    author_name = f'{author.first_name} {author.last_name}' if author else '—'
    text_preview = message.text[:120].replace('\n', ' ')

    sent = 0
    for m in members:
        if m.user_id == message.user_id:
            continue
        if m.is_guest:
            continue

        if mentioned_user_ids and m.user_id in mentioned_user_ids:
            title = f'💬 {author_name} упомянул(а) вас'
            body = text_preview
            tag = f'mention-{message.id}'
        else:
            title = f'💬 {author_name}'
            body = f'{message.project.name}\n{text_preview}'
            tag = f'msg-{message.id}'

        sent += send_push_to_user(
            user_id=m.user_id,
            title=title,
            body=body,
            url=f'/project/{message.project_id}?mark_read=1#chat',
            tag=tag,
        )

    return sent

# ============================================================
#  ХЕЛПЕРЫ ДЛЯ ТЕХПОДДЕРЖКИ
# ============================================================

def notify_new_support_message(ticket, message, for_admin=True):
    """Push: новое сообщение в тикете поддержки.

    Параметры:
        ticket: SupportTicket
        message: SupportMessage (только что созданное)
        for_admin: True — уведомляем админов о новом обращении юзера,
                   False — уведомляем юзера об ответе админа.
    """
    from models import User

    # Кому шлём
    if for_admin:
        # Всем админам и супервизорам
        recipients = User.query.filter(
            User.role.in_(['admin', 'supervisor']),
            User.is_active.is_(True),
        ).all()
        title = f'🎫 Новое обращение #{ticket.id}'
        body = f'От: {ticket.user.full_name}\n{message.text[:100]}'
        url = f'/support/ticket/{ticket.id}'
        tag = f'support-ticket-{ticket.id}'
    else:
        # Автору тикета — об ответе админа
        recipients = [ticket.user] if ticket.user else []
        title = f'💬 Ответ поддержки по обращению #{ticket.id}'
        body = f'{message.author.full_name}: {message.text[:100]}'
        url = f'/support/ticket/{ticket.id}'
        tag = f'support-ticket-{ticket.id}'

    sent = 0
    for recipient in recipients:
        # Автору сообщения не шлём
        if recipient.id == message.author_id:
            continue
        sent += send_push_to_user(
            user_id=recipient.id,
            title=title,
            body=body,
            url=url,
            tag=tag,
        )
    return sent