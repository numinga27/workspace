from datetime import datetime
from flask import (
    Blueprint, redirect, url_for, flash, session,
    jsonify, request, render_template, send_from_directory, abort, current_app
)
from sqlalchemy import func

from extensions import db
from models import Message, MessageMention, User, ProjectMember, Project, Notification
from decorators import login_required
from utils import (
    check_project_access, mark_project_as_read,
    get_project_mentionable_users, parse_mentions_in_text,
    mark_mentions_as_read, get_unread_mentions_by_project,
    is_project_guest,
    get_user_projects, utcnow,
)
from services.push import notify_new_message, send_push_to_user

bp = Blueprint('chat', __name__)


# ============================================================
#  ОТПРАВКА СООБЩЕНИЯ
# ============================================================

@bp.route('/project/<int:project_id>/send_message', methods=['POST'])
@login_required
def send_message(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    text = (request.form.get('message') or '').strip()
    user_id = session['user_id']
    reply_to_id = request.form.get('reply_to_id', type=int)

    uploads = [f for f in request.files.getlist('attachments') if f and f.filename]
    if not text and not uploads:
        flash('Введите сообщение или прикрепите файл.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project_id) + '#chat')

    from services.attachments import save_attachment, MAX_FILES_PER_MESSAGE
    if len(uploads) > MAX_FILES_PER_MESSAGE:
        flash(f'Максимум {MAX_FILES_PER_MESSAGE} вложений.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project_id) + '#chat')

    # Цитата должна быть из этого же проекта
    if reply_to_id:
        parent = Message.query.filter_by(id=reply_to_id, project_id=project_id).first()
        if not parent:
            reply_to_id = None

    # Текст сообщения: если нет текста — показываем имена файлов
    display_text = text
    if not display_text and uploads:
        names = [f.filename for f in uploads]
        if len(names) == 1:
            display_text = '📎 ' + names[0]
        else:
            display_text = '📎 ' + ', '.join(names) + ' (' + str(len(names)) + ' вложен.)'

    message = Message(
        text=display_text or '',
        user_id=user_id,
        project_id=project_id,
        reply_to_id=reply_to_id,
    )
    db.session.add(message)
    db.session.flush()

    for up in uploads:
        save_attachment(up, uploaded_by=user_id,
                        project_id=project_id, message_id=message.id)

    mentioned_user_ids = parse_mentions_in_text(text, project_id) if text else set()
    mentioned_user_ids.discard(user_id)
    for uid in mentioned_user_ids:
        db.session.add(MessageMention(
            message_id=message.id, user_id=uid,
            project_id=project_id, is_read=False,
        ))

    db.session.commit()

    # Создаём уведомления для всех участников проекта (кроме автора)
    try:
        members = ProjectMember.query.filter_by(project_id=project_id).all()
        for m in members:
            if m.user_id == user_id:
                continue
            if m.is_guest:
                continue
            # Проверяем, не отправлял ли пользователь уже сообщение — не дублируем
            existing = Notification.query.filter_by(
                user_id=m.user_id,
                type='chat',
                related_type='message',
                related_id=message.id,
            ).first()
            if not existing:
                author_name = f'{user.first_name} {user.last_name}'
                n = Notification(
                    user_id=m.user_id,
                    type='chat',
                    title=f'💬 {author_name}',
                    body=message.text[:100],
                    url=url_for('projects.view_project', project_id=project_id) + '#chat',
                    related_type='message',
                    related_id=message.id,
                    project_id=project_id,
                    from_user_id=user_id,
                    is_read=False,
                )
                db.session.add(n)
        db.session.commit()
    except Exception as e:
        print(f'⚠️ Ошибка создания уведомлений чата: {e}')
        db.session.rollback()

    mark_project_as_read(user_id, project_id)
    mark_mentions_as_read(user_id, project_id)

    try:
        push_data_list = notify_new_message(message, mentioned_user_ids=mentioned_user_ids)
        for push_data in push_data_list or []:
            send_push_to_user(
                user_id=push_data['user_id'],
                title=push_data['title'],
                body=push_data['body'],
                url=push_data['url'],
                tag=push_data.get('tag'),
            )
    except Exception as e:
        print(f'⚠️ Ошибка отправки push: {e}')

    return redirect(url_for('projects.view_project', project_id=project_id) + '#chat')


# ============================================================
#  РЕДАКТИРОВАНИЕ СООБЩЕНИЯ
# ============================================================

@bp.route('/project/<int:project_id>/edit_message/<int:msg_id>', methods=['POST'])
@login_required
def edit_message(project_id, msg_id):
    if not check_project_access(project_id):
        return jsonify({'error': 'Нет доступа.'}), 403

    msg = Message.query.get_or_404(msg_id)
    if msg.project_id != project_id:
        return jsonify({'error': 'Нет доступа.'}), 403

    user = db.session.get(User, session['user_id'])
    if msg.user_id != user.id and not user.is_privileged:
        return jsonify({'error': 'Нет доступа.'}), 403

    text = (request.form.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Сообщение не может быть пустым.'}), 400

    msg.text = text
    msg.updated_at = utcnow()
    db.session.commit()

    # AJAX-запрос → JSON, обычный → редирест
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'text': text})

    flash('Сообщение обновлено.', 'success')
    return redirect(url_for('projects.view_project', project_id=project_id) + '#chat')


# ============================================================
#  УДАЛЕНИЕ СООБЩЕНИЯ
# ============================================================

@bp.route('/project/<int:project_id>/delete_message/<int:msg_id>', methods=['POST'])
@login_required
def delete_message(project_id, msg_id):
    if not check_project_access(project_id):
        return jsonify({'error': 'Нет доступа.'}), 403

    msg = Message.query.get_or_404(msg_id)
    if msg.project_id != project_id:
        return jsonify({'error': 'Нет доступа.'}), 403

    user = db.session.get(User, session['user_id'])
    if msg.user_id != user.id and not user.is_privileged:
        return jsonify({'error': 'Нет доступа.'}), 403

    db.session.delete(msg)
    db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})

    flash('Сообщение удалено.', 'success')
    return redirect(url_for('projects.view_project', project_id=project_id) + '#chat')


# ============================================================
#  СКАЧИВАНИЕ ВЛОЖЕНИЯ
# ============================================================

@bp.route('/attachment/<int:file_id>/download')
@login_required
def download_attachment(file_id):
    from models import File
    from services.attachments import can_view_attachment

    f = File.query.get_or_404(file_id)
    user = db.session.get(User, session['user_id'])
    if not can_view_attachment(f, user):
        abort(403)
    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'],
        f.stored_name,
        download_name=f.original_name,
    )


# ============================================================
#  ОТМЕТКА ЧАТА ПРОЧИТАННЫМ
# ============================================================

@bp.route('/project/<int:project_id>/mark_read', methods=['POST'])
@login_required
def mark_read(project_id):
    if not check_project_access(project_id):
        return jsonify({'success': False}), 403

    mark_project_as_read(session['user_id'], project_id)
    mark_mentions_as_read(session['user_id'], project_id)
    return jsonify({'success': True})


# ============================================================
#  API: ПОИСК УЧАСТНИКОВ ПРОЕКТА ДЛЯ @УПОМИНАНИЙ
# ============================================================

@bp.route('/project/<int:project_id>/api/mention/search')
@login_required
def api_mention_search(project_id):
    """Поиск участников проекта для автокомплита @.

    GET-параметры:
      q — строка (может быть пустой — вернём всех).
      limit — максимум (по умолчанию 15).

    Возвращает JSON-массив:
      {id, name, email, role_display, company}

    Включает:
      - участников проекта (команда + АМ Станко);
      - всех админов и супервизоров (даже если не в проекте).
    """
    if not check_project_access(project_id):
        return jsonify([])

    q = request.args.get('q', '').strip().lower()
    limit = min(int(request.args.get('limit', 15) or 15), 50)

    mentionable = get_project_mentionable_users(project_id)

    results = []
    for user, member in mentionable:
        full_name = f'{user.first_name} {user.last_name}'
        if q:
            haystack = f'{full_name} {user.email} {user.company or ""}'.lower()
            if q not in haystack:
                continue

        # Для админов/супервизоров member=None — показываем их системную роль
        if member:
            role_display = member.role_display
        elif user.is_admin:
            role_display = 'Администратор'
        elif user.is_supervisor:
            role_display = 'Супервизор'
        else:
            role_display = 'Участник'

        results.append({
            'id': user.id,
            'name': full_name,
            'email': user.email,
            'company': user.company or '',
            'role_display': role_display,
        })

        if len(results) >= limit:
            break

    return jsonify(results)


# ============================================================
#  СТРАНИЦА «МОИ УПОМИНАНИЯ»
# ============================================================

@bp.route('/my-mentions')
@login_required
def my_mentions():
    user_id = session['user_id']
    user = User.query.get(user_id)

    mentions = MessageMention.query.filter_by(user_id=user_id)\
        .order_by(MessageMention.is_read.asc(),
                  MessageMention.created_at.desc())\
        .limit(200).all()

    by_project = {}
    for m in mentions:
        pid = m.project_id
        if pid not in by_project:
            project = Project.query.get(pid)
            by_project[pid] = {
                'project': project,
                'mentions': [],
                'unread_count': 0,
            }
        by_project[pid]['mentions'].append(m)
        if not m.is_read:
            by_project[pid]['unread_count'] += 1

    sorted_projects = sorted(
        by_project.items(),
        key=lambda item: (-item[1]['unread_count'],
                          -max((m.created_at.timestamp() if m.created_at else 0)
                               for m in item[1]['mentions']))
    )

    author_ids = {m.message.user_id for m in mentions if m.message}
    authors = {
        u.id: u for u in User.query.filter(User.id.in_(author_ids)).all()
    } if author_ids else {}

    return render_template('my_mentions.html',
                           user=user,
                           grouped_projects=sorted_projects,
                           authors=authors,
                           total_unread=get_unread_mentions_by_project(user_id),
                           projects=get_user_projects(user))


# ============================================================
#  ОТМЕТИТЬ ВСЕ УПОМИНАНИЯ ПРОЧИТАННЫМИ
# ============================================================

@bp.route('/my-mentions/mark-all-read', methods=['POST'])
@login_required
def my_mentions_mark_all_read():
    user_id = session['user_id']

    updated = MessageMention.query.filter_by(
        user_id=user_id,
        is_read=False,
    ).update({'is_read': True}, synchronize_session=False)

    db.session.commit()

    if updated > 0:
        flash(f'Отмечено как прочитанное: {updated}.', 'success')
    else:
        flash('Все упоминания уже прочитаны.', 'info')

    return redirect(url_for('chat.my_mentions'))


# ============================================================
#  МОИ УВЕДОМЛЕНИЯ
# ============================================================

@bp.route('/my-notifications')
@login_required
def my_notifications():
    user_id = session['user_id']
    user = User.query.get(user_id)

    # ===== ПОЛУЧЕННЫЕ =====
    received = Notification.query.filter_by(
        user_id=user_id
    ).order_by(
        Notification.is_read.asc(),
        Notification.created_at.desc()
    ).limit(100).all()

    by_project = {}
    for n in received:
        pid = n.project_id or 0
        if pid not in by_project:
            project = Project.query.get(pid) if pid else None
            by_project[pid] = {
                'project': project,
                'notifications': [],
                'unread_count': 0,
            }
        by_project[pid]['notifications'].append(n)
        if not n.is_read:
            by_project[pid]['unread_count'] += 1

    sorted_projects = sorted(
        by_project.items(),
        key=lambda item: (-item[1]['unread_count'],
                          -max((n.created_at.timestamp() if n.created_at else 0)
                               for n in item[1]['notifications']))
    )

    total_unread = Notification.query.filter_by(
        user_id=user_id, is_read=False
    ).count()

    # ===== ОТПРАВЛЕННЫЕ (только admin/supervisor) =====
    sent = []
    can_manage = user.role in ('admin', 'supervisor')
    if can_manage:
        sent = Notification.query.filter_by(
            from_user_id=user_id
        ).order_by(
            Notification.created_at.desc()
        ).limit(100).all()

    return render_template('my_notifications.html',
                           user_id=user_id,
                           user_role=user.role,
                           grouped_projects=sorted_projects,
                           total_unread=total_unread,
                           sent_notifications=sent,
                           can_manage=can_manage,
                           projects=get_user_projects(User.query.get(user_id)))


@bp.route('/my-notifications/mark-all-read', methods=['POST'])
@login_required
def my_notifications_mark_all_read():
    user_id = session['user_id']

    updated = Notification.query.filter_by(
        user_id=user_id,
        is_read=False,
    ).update({'is_read': True}, synchronize_session=False)

    db.session.commit()

    if updated > 0:
        flash(f'Отмечено как прочитанное: {updated}.', 'success')
    else:
        flash('Все уведомления уже прочитаны.', 'info')

    return redirect(url_for('chat.my_notifications'))


# ============================================================
#  УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ (admin/supervisor)
# ============================================================

@bp.route('/notification/<int:nid>/delete', methods=['POST'])
@login_required
def delete_notification(nid):
    """Удалить уведомление (только admin)."""
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        return jsonify({'error': 'Нет доступа.'}), 403

    n = Notification.query.get_or_404(nid)
    db.session.delete(n)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/notification/<int:nid>/edit')
@login_required
def edit_notification(nid):
    """Показать форму редактирования (только admin)."""
    user = User.query.get(session['user_id'])
    if user.role not in ('admin', 'supervisor'):
        return jsonify({'error': 'Нет доступа.'}), 403

    n = Notification.query.get_or_404(nid)
    return jsonify({
        'id': n.id,
        'title': n.title,
        'body': n.body or '',
        'type': n.type,
        'url': n.url or '/my-notifications',
    })


@bp.route('/notification/<int:nid>/edit', methods=['POST'])
@login_required
def save_edit_notification(nid):
    """Сохранить изменения в уведомлении (только admin)."""
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        return jsonify({'error': 'Нет доступа.'}), 403

    n = Notification.query.get_or_404(nid)
    n.title = (request.form.get('title') or '').strip()
    n.body = (request.form.get('body') or '').strip()
    n.type = request.form.get('type', n.type)
    n.url = request.form.get('url', n.url)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/notification/<int:nid>/readers')
@login_required
def notification_readers(nid):
    """Кто прочитал уведомление (только admin)."""
    user = User.query.get(session['user_id'])
    if user.role != 'admin':
        return jsonify({'error': 'Нет доступа.'}), 403

    n = Notification.query.get_or_404(nid)

    # Все пользователи, кому отправлено это уведомление
    total_sent = Notification.query.filter_by(
        type=n.type,
        title=n.title,
        body=n.body,
        from_user_id=n.from_user_id,
    ).count()

    # Кто прочитал
    readers = Notification.query.filter_by(
        type=n.type,
        title=n.title,
        body=n.body,
        from_user_id=n.from_user_id,
        is_read=True,
    ).with_entities(Notification.user_id).all()
    reader_ids = [r[0] for r in readers]

    readers_info = []
    if reader_ids:
        users = User.query.filter(User.id.in_(reader_ids)).all()
        for u in users:
            notif = Notification.query.filter_by(user_id=u.id, type=n.type, title=n.title).first()
            readers_info.append({
                'id': u.id,
                'name': f'{u.first_name} {u.last_name}',
                'role': u.role_display,
                'read_at': notif.created_at.isoformat() if notif and notif.created_at else None,
            })

    # Кто не прочитал
    unread_users = User.query.filter(
        User.id.notin_(reader_ids),
        User.is_active == True,
    ).all()

    return jsonify({
        'total_sent': total_sent,
        'read_count': len(readers),
        'readers': readers_info,
        'unread_count': len(unread_users),
        'unread_user_ids': [u.id for u in unread_users],
    })