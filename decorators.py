from functools import wraps
from flask import session, flash, redirect, url_for
from models import User


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('auth.login'))
        user = User.query.get(session['user_id'])
        if user.role != 'admin':
            flash('Доступ запрещен. Только для руководителя.', 'danger')
            return redirect(url_for('dashboard.dashboard'))
        return f(*args, **kwargs)
    return decorated_function