"""Сервис web-push уведомлений (PWA).

Использует pywebpush для отправки пушей через Apple Push Service / Mozilla.
ВНИМАНИЕ: Функции notify_* теперь НЕ отправляют push, а возвращают данные
для фоновой отправки через Celery (send_push_async.delay).
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


# ============================================================
#  НИЗКОУРОВНЕВАЯ ОТПРАВКА (синхронная, используется Celery)
# ============================================================

def send_push_to_user(user_id, title, body, url=None, tag=None, icon=None):
    """Отправить push-уведомление всем активным подпискам пользователя.
    
    ВНИМАНИЕ: Эта функция синхронная. Вызывайте её из Celery-задачи
    (send_push_async), а не напрямую из blueprint'ов.
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
#  ХЕЛПЕРЫ ДЛЯ КОНКРЕТНЫХ СОБЫТИЙ (возвращают данные, не отправляют)
# ============================================================

def notify_new_task(task, poster):
    """Возвращает dict для отправки push о новой задаче.
    
    Использование в blueprint:
        push_data = notify_new_task(task, poster)
        if push_data:
            send_push_async.delay(**push_data)
    """
    if not task.assigned_to:
        return None

    from models import User
    assignee = User.query.get(task.assigned_to)
    if not assignee:
        return None

    if poster and assignee.id == poster.id:
        return None

    project_name = task.project.name if task.project else '—'
    due_text = (
        f'Дедлайн: {task.due_date.strftime("%d.%m.%Y")}'
        if task.due_date else 'Без дедлайна'
    )

    return {
        'user_id': assignee.id,
        'title': '📋 Новая задача',
        'body': f'{task.title}\n{project_name} · {due_text}',
        'url': f'/task/{task.id}',
        'tag': f'task-{task.id}',
    }


def notify_new_subtask(subtask, poster):
    """Возвращает dict для отправки push о новой подзадаче."""
    if not subtask.assigned_to:
        return None

    from models import User
    assignee = User.query.get(subtask.assigned_to)
    if not assignee:
        return None

    if poster and assignee.id == poster.id:
        return None

    project_name = subtask.project.name if subtask.project else '—'
    parent_title = subtask.parent_task.title if subtask.parent_task else ''

    return {
        'user_id': assignee.id,
        'title': '📋 Новая подзадача',
        'body': f'{subtask.title}\nВ задаче: {parent_title} · {project_name}',
        'url': f'/task/{subtask.id}',
        'tag': f'subtask-{subtask.id}',
    }


def notify_new_message(message, mentioned_user_ids=None):
    """Возвращает СПИСОК dict для отправки push о новом сообщении в чате.
    
    Получатели:
    - все участники проекта (кроме гостей и автора);
    - упомянутые пользователи (даже если они не в проекте — например, админы).
    
    Использование в blueprint:
        push_data_list = notify_new_message(message, mentioned_user_ids=...)
        if push_data_list:
            for push_data in push_data_list:
                send_push_async.delay(**push_data)
    """
    if not message.project:
        return []

    from models import ProjectMember, User

    members = ProjectMember.query.filter_by(project_id=message.project_id).all()

    author = message.author
    author_name = f'{author.first_name} {author.last_name}' if author else '—'
    text_preview = message.text[:120].replace('\n', ' ')

    result = []
    seen = set()  # чтобы не дублировать получателей
    mentioned_user_ids = mentioned_user_ids or set()

    # 1. Участники проекта (без гостей, без автора)
    for m in members:
        if m.user_id == message.user_id:
            continue
        if m.is_guest:
            continue
        if m.user_id in seen:
            continue
        seen.add(m.user_id)

        if m.user_id in mentioned_user_ids:
            title = f'💬 {author_name} упомянул(а) вас'
            body = text_preview
            tag = f'mention-{message.id}'
        else:
            title = f'💬 {author_name}'
            body = f'{message.project.name}\n{text_preview}'
            tag = f'msg-{message.id}'

        result.append({
            'user_id': m.user_id,
            'title': title,
            'body': body,
            'url': f'/project/{message.project_id}?mark_read=1#chat',
            'tag': tag,
        })

    # 2. Упомянутые, которых нет в проекте (админы/супервизоры)
    for uid in mentioned_user_ids:
        if uid == message.user_id:
            continue
        if uid in seen:
            continue
        seen.add(uid)

        # Проверяем, что пользователь существует и активен
        user = User.query.get(uid)
        if not user or not user.is_active:
            continue

        result.append({
            'user_id': uid,
            'title': f'💬 {author_name} упомянул(а) вас',
            'body': text_preview,
            'url': f'/project/{message.project_id}?mark_read=1#chat',
            'tag': f'mention-{message.id}',
        })

    return result


# ============================================================
#  ХЕЛПЕРЫ ДЛЯ ТЕХПОДДЕРЖКИ (возвращают данные, не отправляют)
# ============================================================

def notify_new_support_message(ticket, message, for_admin=True):
    """Возвращает СПИСОК dict для отправки push о новом сообщении в тикете.
    
    Параметры:
        ticket: SupportTicket
        message: SupportMessage (только что созданное)
        for_admin: True — уведомляем админов о новом обращении юзера,
                   False — уведомляем юзера об ответе админа.
    """
    from models import User

    result = []

    if for_admin:
        recipients = User.query.filter(
            User.role.in_(['admin', 'supervisor']),
            User.is_active.is_(True),
        ).all()
        title = f'🎫 Новое обращение #{ticket.id}'
        body = f'От: {ticket.user.full_name}\n{message.text[:100]}'
        url = f'/support/ticket/{ticket.id}'
        tag = f'support-ticket-{ticket.id}'
    else:
        recipients = [ticket.user] if ticket.user else []
        title = f'💬 Ответ поддержки по обращению #{ticket.id}'
        body = f'{message.author.full_name}: {message.text[:100]}'
        url = f'/support/ticket/{ticket.id}'
        tag = f'support-ticket-{ticket.id}'

    for recipient in recipients:
        if recipient.id == message.author_id:
            continue
        result.append({
            'user_id': recipient.id,
            'title': title,
            'body': body,
            'url': url,
            'tag': tag,
        })

    return result


def notify_new_event(event, recipient_ids, author):
    """Возвращает СПИСОК dict для отправки Push о новом событии.
    
    Параметры:
        event: Event (только что созданное)
        recipient_ids: set() ID пользователей-получателей
        author: User (кто создал событие)
    """
    from models import User

    if not event or not recipient_ids:
        return []

    author_name = f'{author.first_name} {author.last_name}' if author else '—'
    project_name = event.project.name if event.project else '—'

    # Форматируем дату
    if event.all_day:
        time_str = event.start_time.strftime('%d.%m.%Y') + ' (весь день)'
    else:
        time_str = event.start_time.strftime('%d.%m.%Y %H:%M')
        if event.end_time:
            time_str += f'–{event.end_time.strftime("%H:%M")}'

    result = []
    for uid in recipient_ids:
        user = User.query.get(uid)
        if not user or not user.is_active:
            continue

        result.append({
            'user_id': uid,
            'title': f'📅 {event.title}',
            'body': f'{time_str}\nПроект: {project_name}\nОт: {author_name}',
            'url': f'/project/{event.project_id}?_tab=calendar',
            'tag': f'event-{event.id}',
        })

    return result