from flask import Blueprint, redirect, url_for, flash, session, request
from datetime import datetime

from models import User, Notification
from extensions import db
from decorators import login_required
from services.email import check_and_send_deadline_notifications

bp = Blueprint('admin', __name__)


@bp.route('/admin/send-deadline-notifications', methods=['POST'])
@login_required
def manual_send_notifications():
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        flash('Доступ запрещён.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    count = check_and_send_deadline_notifications()
    flash(f'Отправлено уведомлений: {count}. Проверьте лог.', 'success')
    return redirect(url_for('dashboard.dashboard'))


@bp.route('/admin/send-notification', methods=['POST'])
@login_required
def admin_send_notification():
    """Отправить уведомление всем пользователям или выбранному."""
    user = User.query.get(session['user_id'])
    if user.role not in ('admin', 'supervisor'):
        flash('Доступ запрещён.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    title = (request.form.get('title') or '').strip()
    body = (request.form.get('body') or '').strip()
    target = request.form.get('target', 'all')  # 'all' или конкретный user_id
    notification_type = request.form.get('type', 'admin')  # 'admin' или 'system'

    if not title:
        flash('Введите заголовок уведомления.', 'warning')
        return redirect(url_for('dashboard.dashboard'))

    # Определяем URL куда переходить
    url = request.form.get('url', '/my-notifications')

    if target == 'all':
        # Отправляем всем пользователям
        users = User.query.filter_by(is_active=True).all()
    else:
        # Отправляем конкретному пользователю
        try:
            uid = int(target)
            users = [User.query.get(uid)] if uid else []
        except (ValueError, TypeError):
            users = []

    created = 0
    for u in users:
        if not u:
            continue
        # Не отправляем себе
        if u.id == user.id:
            continue
        # Не дублируем для одного пользователя за последние 5 минут
        existing = Notification.query.filter(
            Notification.user_id == u.id,
            Notification.type == notification_type,
            Notification.title == title,
            Notification.created_at >= datetime.utcnow().replace(second=0, microsecond=0),
        ).first()
        if existing:
            continue

        n = Notification(
            user_id=u.id,
            type=notification_type,
            title=title,
            body=body,
            url=url,
            from_user_id=user.id,
            is_read=False,
        )
        db.session.add(n)
        created += 1

    db.session.commit()
    
    # Отправляем push-уведомления
    if created > 0:
        try:
            from services.push import send_push_to_user
            for u in users:
                if not u or u.id == user.id:
                    continue
                if Notification.query.filter_by(
                    user_id=u.id,
                    type=notification_type,
                    title=title,
                    from_user_id=user.id,
                ).first():
                    send_push_to_user(
                        user_id=u.id,
                        title=title,
                        body=body or title,
                        url=url,
                        tag=f'admin-{notification_type}',
                    )
        except Exception as e:
            print(f'⚠️ Ошибка push: {e}')
    
    flash(f'Уведомление отправлено: {created} пользовател(ю/ей).', 'success')
    return redirect(url_for('dashboard.dashboard'))