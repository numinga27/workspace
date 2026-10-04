from functools import wraps
from flask import session, flash, redirect, url_for
from models import User


def login_required(f):
    """Требует авторизации. Проверяет только наличие user_id в сессии."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def privileged_required(f):
    """Доступ для админа И супервизора.

    Используется в разделах, где нужны права администратора:
    - управление пользователями
    - управление справочниками
    - настройки системы
    - статистика по всей системе

    Симметрично проверке `user.is_privileged` в шаблонах.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('auth.login'))

        user = User.query.get(session['user_id'])
        if not user or not user.is_privileged:
            flash('Доступ запрещён. Требуются права администратора или супервизора.', 'danger')
            return redirect(url_for('dashboard.dashboard'))

        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Строгая проверка: ТОЛЬКО главный администратор (role='admin').

    Используется для особых случаев:
    - удаление других администраторов
    - назначение новых админов
    - критичные системные операции

    В большинстве случаев нужен `privileged_required`, а не этот декоратор.
    Оставлен для совместимости и точечного контроля.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('auth.login'))

        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Доступ запрещён. Только для главного администратора.', 'danger')
            return redirect(url_for('dashboard.dashboard'))

        return f(*args, **kwargs)
    return decorated_function