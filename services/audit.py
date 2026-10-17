"""Сервис логирования действий пользователей.

Используется для записи в ActivityLog.
Правила:
  - логируются только CRUD-действия и login/logout
  - действия админа НЕ логируются (по требованию)
  - очистка записей старше 30 дней — через cron
"""
from datetime import timedelta

from flask import request, session

from extensions import db
from models import ActivityLog, User
from utils import utcnow


def _get_client_ip():
    """IP клиента с учётом прокси (nginx)."""
    if not request:
        return None
    # nginx передаёт реальный IP в X-Real-IP / X-Forwarded-For
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip[:45]

    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()[:45]

    return (request.remote_addr or '')[:45]


def _get_user_agent():
    if not request:
        return None
    ua = request.headers.get('User-Agent') or ''
    return ua[:255]


def log_action(action, target_type=None, target_id=None,
               target_name=None, details=None):
    """Записать действие в журнал.

    Пропускает запись, если:
      - действие выполнил админ (по требованию — не логируем админов)
      - действие вообще без сессии (например, внутренний вызов)

    Параметры:
        action: строка действия ('create_project', 'edit_task', ...)
        target_type: тип объекта ('project', 'task', 'customer', ...)
        target_id: ID объекта
        target_name: имя объекта (сохраняем на момент действия)
        details: дополнительное описание
    """
    user_id = session.get('user_id')
    if not user_id:
        return  # анонимные действия не логируем

    user = User.query.get(user_id)
    if not user:
        return

    # ← НЕ логируем действия администратора
    if user.role == 'admin':
        return

    log = ActivityLog(
        user_id=user.id,
        user_name=f'{user.first_name} {user.last_name}'[:120],
        user_role=user.role,
        action=action[:50],
        target_type=(target_type or '')[:30] or None,
        target_id=target_id,
        target_name=(target_name or '')[:200] or None,
        details=details,
        ip_address=_get_client_ip(),
        user_agent=_get_user_agent(),
        created_at=utcnow(),
    )
    db.session.add(log)
    db.session.commit()


def cleanup_old_logs(days=30):
    """Удаляет записи старше `days` дней.

    Вызывается из cron (раз в день).
    Возвращает количество удалённых записей.
    """
    cutoff = utcnow() - timedelta(days=days)
    deleted = ActivityLog.query.filter(
        ActivityLog.created_at < cutoff
    ).delete(synchronize_session=False)
    db.session.commit()
    return deleted