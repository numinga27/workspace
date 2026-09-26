from flask import Blueprint, redirect, url_for, flash, session

from models import User
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