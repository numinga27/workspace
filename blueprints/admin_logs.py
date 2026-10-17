from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, session
from sqlalchemy import func

from extensions import db
from models import User, ActivityLog
from decorators import login_required, admin_required
from utils import utcnow, get_user_projects


bp = Blueprint('admin_logs', __name__, url_prefix='/admin/logs')


# ============================================================
#  ЖУРНАЛ ДЕЙСТВИЙ
# ============================================================

@bp.route('/')
@login_required
@admin_required          # ← только role='admin'
def logs_view():
    """Журнал действий пользователей.

    Доступ: только главный администратор.
    Фильтры: пользователь, действие, дата от, дата до.
    Пагинация: 100 записей на страницу.
    """
    current_user = User.query.get(session['user_id'])

    # Параметры фильтра
    filter_user = request.args.get('user', '').strip()
    filter_action = request.args.get('action', '').strip()
    filter_from = request.args.get('date_from', '').strip()
    filter_to = request.args.get('date_to', '').strip()
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = 100

    query = ActivityLog.query

    # Фильтр по пользователю
    if filter_user:
        try:
            uid = int(filter_user)
            query = query.filter(ActivityLog.user_id == uid)
        except ValueError:
            pass

    # Фильтр по действию
    if filter_action:
        query = query.filter(ActivityLog.action == filter_action)

    # Фильтр по дате от
    if filter_from:
        try:
            d = datetime.strptime(filter_from, '%Y-%m-%d')
            query = query.filter(ActivityLog.created_at >= d)
        except ValueError:
            pass

    # Фильтр по дате до (включительно — до 23:59:59)
    if filter_to:
        try:
            d = datetime.strptime(filter_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(ActivityLog.created_at < d)
        except ValueError:
            pass

    total = query.count()
    logs = query.order_by(ActivityLog.created_at.desc())\
        .offset((page - 1) * per_page)\
        .limit(per_page)\
        .all()

    # ← ВСЕ активные пользователи для фильтра
    # (не только те, у кого есть записи — чтобы всегда был доступен выбор)
    filter_users = User.query.filter(User.is_active.is_(True))\
        .order_by(User.last_name.asc(), User.first_name.asc()).all()

    # ← Счётчик записей у каждого пользователя (для отображения рядом с именем)
    user_counts_query = db.session.query(
        ActivityLog.user_id,
        func.count(ActivityLog.id)
    ).group_by(ActivityLog.user_id).all()
    user_counts = {uid: cnt for uid, cnt in user_counts_query if uid is not None}

    # Список доступных действий
    available_actions = sorted(ActivityLog.ACTIONS_DISPLAY.items(),
                               key=lambda x: x[1])

    # Инфо о старой записи
    cutoff = utcnow() - timedelta(days=30)

    return render_template('admin/logs.html',
                           user=current_user,
                           logs=logs,
                           total=total,
                           page=page,
                           per_page=per_page,
                           total_pages=(total + per_page - 1) // per_page,
                           filter_user=filter_user,
                           filter_action=filter_action,
                           filter_from=filter_from,
                           filter_to=filter_to,
                           filter_users=filter_users,
                           user_counts=user_counts,
                           available_actions=available_actions,
                           retention_cutoff=cutoff,
                           projects=get_user_projects(current_user))