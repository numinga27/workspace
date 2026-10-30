from datetime import datetime
from flask import (
    Blueprint, redirect, url_for, flash, session,
    jsonify, request, render_template, send_from_directory, abort, current_app
)

from extensions import db
from models import Message, MessageMention, User, ProjectMember, Project
from decorators import login_required
from utils import (
    check_project_access, mark_project_as_read,
    get_project_mentionable_users, parse_mentions_in_text,
    mark_mentions_as_read, get_unread_mentions_by_project,
    is_project_guest,
    get_user_projects,
)
from services.push import notify_new_message
from services.tasks import send_push_async  # ← ФОНОВАЯ ЗАДАЧА

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

    mark_project_as_read(user_id, project_id)
    mark_mentions_as_read(user_id, project_id)

    try:
        push_data_list = notify_new_message(message, mentioned_user_ids=mentioned_user_ids)
        for push_data in push_data_list or []:
            send_push_async.delay(**push_data)
    except Exception as e:
        print(f'⚠️ Ошибка отправки push: {e}')

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