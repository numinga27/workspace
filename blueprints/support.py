from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, session, request, jsonify,
)

from extensions import db
from models import User, SupportTicket, SupportMessage
from decorators import login_required
from utils import utcnow
from services.push import notify_new_support_message

bp = Blueprint('support', __name__, url_prefix='/support')


# ============================================================
#  ХЕЛПЕРЫ
# ============================================================

def _is_privileged(user):
    return user and user.role in ('admin', 'supervisor')


def _get_or_create_ticket(user):
    """Возвращает открытый тикет пользователя или создаёт новый."""
    ticket = SupportTicket.query.filter_by(
        user_id=user.id, status='open'
    ).order_by(SupportTicket.created_at.desc()).first()

    if not ticket:
        ticket = SupportTicket(
            user_id=user.id,
            subject='Обращение в поддержку',
            status='open',
        )
        db.session.add(ticket)
        db.session.commit()

    return ticket


# ============================================================
#  ПОДДЕРЖКА ДЛЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@bp.route('/')
@login_required
def my_tickets():
    """Список тикетов текущего пользователя."""
    user = User.query.get(session['user_id'])

    # Админ/супервизор попадает на страницу всех тикетов
    if _is_privileged(user):
        return redirect(url_for('support.admin_tickets'))

    tickets = SupportTicket.query.filter_by(user_id=user.id)\
        .order_by(SupportTicket.updated_at.desc()).all()

    return render_template('support/my_tickets.html',
                           user=user,
                           tickets=tickets)


@bp.route('/new', methods=['POST'])
@login_required
def create_ticket():
    """Пользователь создаёт новый тикет (или пишет в текущий)."""
    user = User.query.get(session['user_id'])

    if _is_privileged(user):
        flash('Администраторы не создают тикеты.', 'warning')
        return redirect(url_for('support.admin_tickets'))

    text = (request.form.get('text') or '').strip()
    if not text:
        flash('Введите текст обращения.', 'warning')
        return redirect(url_for('support.my_tickets'))

    ticket = _get_or_create_ticket(user)

    msg = SupportMessage(
        ticket_id=ticket.id,
        author_id=user.id,
        role='user',
        text=text,
        is_read=False,
    )
    db.session.add(msg)

    ticket.updated_at = utcnow()
    ticket.unread_for_admin = (ticket.unread_for_admin or 0) + 1
    ticket.status = 'open'

    db.session.commit()

    # ← Push-уведомление всем админам
    try:
        notify_new_support_message(ticket, msg, for_admin=True)
    except Exception as e:
        print(f'⚠️ Ошибка push support (new): {e}')

    flash('Сообщение отправлено в поддержку.', 'success')
    return redirect(url_for('support.ticket_detail', ticket_id=ticket.id))


@bp.route('/ticket/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def ticket_detail(ticket_id):
    """Открыть тикет. POST — отправить сообщение."""
    user = User.query.get(session['user_id'])
    ticket = SupportTicket.query.get_or_404(ticket_id)

    # Доступ: свой тикет или админ
    is_admin = _is_privileged(user)
    if not is_admin and ticket.user_id != user.id:
        flash('Нет доступа к этому обращению.', 'danger')
        return redirect(url_for('support.my_tickets'))

    # Отмечаем прочитанным
    if is_admin:
        SupportMessage.query.filter_by(
            ticket_id=ticket.id, is_read=False
        ).filter(SupportMessage.role == 'user').update(
            {'is_read': True}, synchronize_session=False
        )
        ticket.unread_for_admin = 0
    else:
        SupportMessage.query.filter_by(
            ticket_id=ticket.id, is_read=False
        ).filter(SupportMessage.role == 'admin').update(
            {'is_read': True}, synchronize_session=False
        )
        ticket.unread_for_user = 0

    db.session.commit()

    # POST — новое сообщение
    if request.method == 'POST':
        text = (request.form.get('text') or '').strip()
        if not text:
            flash('Введите сообщение.', 'warning')
            return redirect(url_for('support.ticket_detail', ticket_id=ticket.id))

        role = 'admin' if is_admin else 'user'
        msg = SupportMessage(
            ticket_id=ticket.id,
            author_id=user.id,
            role=role,
            text=text,
            is_read=False,
        )
        db.session.add(msg)

        ticket.updated_at = utcnow()
        if is_admin:
            ticket.unread_for_user = (ticket.unread_for_user or 0) + 1
        else:
            ticket.unread_for_admin = (ticket.unread_for_admin or 0) + 1
            ticket.status = 'open'

        db.session.commit()

        # ← Push-уведомление
        # Если ответил админ → шлём автору тикета
        # Если написал юзер → шлём админам
        try:
            notify_new_support_message(ticket, msg, for_admin=not is_admin)
        except Exception as e:
            print(f'⚠️ Ошибка push support (reply): {e}')

        return redirect(url_for('support.ticket_detail', ticket_id=ticket.id))

    messages = ticket.messages.order_by(SupportMessage.created_at.asc()).all()

    return render_template('support/ticket.html',
                           user=user,
                           ticket=ticket,
                           messages=messages,
                           is_admin=is_admin)


@bp.route('/ticket/<int:ticket_id>/close', methods=['POST'])
@login_required
def close_ticket(ticket_id):
    """Админ закрывает тикет."""
    user = User.query.get(session['user_id'])
    if not _is_privileged(user):
        flash('Нет прав.', 'danger')
        return redirect(url_for('support.my_tickets'))

    ticket = SupportTicket.query.get_or_404(ticket_id)
    ticket.status = 'closed'
    ticket.updated_at = utcnow()
    db.session.commit()

    flash(f'Обращение #{ticket.id} закрыто.', 'success')
    return redirect(url_for('support.admin_tickets'))


# ============================================================
#  АДМИНСКИЕ ФУНКЦИИ
# ============================================================

@bp.route('/admin')
@login_required
def admin_tickets():
    """Список всех тикетов — только для админов."""
    user = User.query.get(session['user_id'])
    if not _is_privileged(user):
        flash('Нет прав.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    status_filter = request.args.get('status', 'open')
    query = SupportTicket.query

    if status_filter == 'open':
        query = query.filter_by(status='open')
    elif status_filter == 'closed':
        query = query.filter_by(status='closed')

    tickets = query.order_by(
        SupportTicket.unread_for_admin.desc(),
        SupportTicket.updated_at.desc()
    ).all()

    total_unread = db.session.query(
        db.func.sum(SupportTicket.unread_for_admin)
    ).scalar() or 0

    return render_template('support/admin_tickets.html',
                           user=user,
                           tickets=tickets,
                           status_filter=status_filter,
                           total_unread=total_unread)


@bp.route('/admin/unread-count')
@login_required
def unread_count():
    """API: количество непрочитанных тикетов — для бейджа в сайдбаре."""
    user = User.query.get(session['user_id'])
    if not _is_privileged(user):
        return jsonify({'count': 0})

    count = db.session.query(
        db.func.sum(SupportTicket.unread_for_admin)
    ).scalar() or 0

    return jsonify({'count': int(count)})