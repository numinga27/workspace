from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy.orm import joinedload

from extensions import db
from models import User, Event, EventRecipient, Task, Milestone, Todo, ProjectMember
from decorators import login_required
from utils import (
    utcnow, check_project_access, check_full_project_access,
    can_manage_project, get_user_projects, is_project_guest,
)

bp = Blueprint('calendar', __name__)


# ============================================================
#  ХЕЛПЕР ДЛЯ ЛОГИРОВАНИЯ
# ============================================================

def _log(action, target=None, target_type=None, target_id=None,
         target_name=None, details=None):
    """Безопасно пишет действие в журнал."""
    try:
        from services.audit import log_action
        log_action(action,
                   target_type=target_type,
                   target_id=target_id or (target.id if target else None),
                   target_name=target_name or (getattr(target, 'title', None) if target else None),
                   details=details)
    except Exception as e:
        print(f'⚠️ Ошибка логирования {action}: {e}')


# ============================================================
#  МОЙ КАЛЕНДАРЬ
# ============================================================

@bp.route('/my-calendar')
@login_required
def my_calendar():
    user = User.query.get(session['user_id'])

    personal_events = Event.query.filter_by(
        event_type='personal', owner_id=user.id
    ).order_by(Event.start_time).all()

    projects = get_user_projects(user)
    project_ids = [p.id for p in projects]

    project_events = Event.query.filter(
        Event.event_type == 'project',
        Event.project_id.in_(project_ids)
    ).options(joinedload(Event.project), joinedload(Event.creator))\
     .order_by(Event.start_time).all() if project_ids else []

    # События, где пользователь — получатель (рассылки)
    recipient_events = db.session.query(Event).join(
        EventRecipient,
        EventRecipient.event_id == Event.id
    ).filter(
        EventRecipient.user_id == user.id,
    ).options(joinedload(Event.project), joinedload(Event.creator))\
     .order_by(Event.start_time).all()

    return render_template('my_calendar.html',
                           user=user,
                           personal_events=personal_events,
                           project_events=project_events,
                           recipient_events=recipient_events,
                           projects=projects,
                           now=utcnow())


@bp.route('/my-calendar/events.json')
@login_required
def my_calendar_json():
    user = User.query.get(session['user_id'])
    events = []

    # ------------------------------------------------
    #  ЛИЧНЫЕ СОБЫТИЯ
    # ------------------------------------------------
    for e in Event.query.filter_by(event_type='personal', owner_id=user.id).all():
        events.append({
            'id': f'personal-{e.id}',
            'title': f'👤 {e.title}',
            'start': e.start_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': e.end_time.strftime('%Y-%m-%dT%H:%M:%S') if e.end_time else None,
            'allDay': e.all_day,
            'backgroundColor': e.color_hex,
            'borderColor': e.color_hex,
            'textColor': '#ffffff',
            'extendedProps': {
                'type': 'personal',
                'description': e.description or ''
            }
        })

    # ------------------------------------------------
    #  СОБЫТИЯ ПРОЕКТОВ (где пользователь — участник)
    # ------------------------------------------------
    projects = get_user_projects(user)
    project_ids = [p.id for p in projects]

    if project_ids:
        project_events = Event.query.filter(
            Event.event_type == 'project',
            Event.project_id.in_(project_ids)
        ).options(joinedload(Event.project), joinedload(Event.creator)).all()

        for e in project_events:
            events.append({
                'id': f'event-{e.id}',
                'title': f'📁 {e.title}',
                'start': e.start_time.strftime('%Y-%m-%dT%H:%M:%S'),
                'end': e.end_time.strftime('%Y-%m-%dT%H:%M:%S') if e.end_time else None,
                'allDay': e.all_day,
                'backgroundColor': e.color_hex,
                'borderColor': e.color_hex,
                'textColor': '#ffffff',
                'extendedProps': {
                    'type': 'project_event',
                    'description': e.description or '',
                    'project': e.project.name if e.project else '',
                    'creator': f"{e.creator.first_name} {e.creator.last_name}" if e.creator else ''
                }
            })

    # ------------------------------------------------
    #  СОБЫТИЯ-РАССЫЛКИ (где пользователь — получатель)
    # ------------------------------------------------
    recipient_events = db.session.query(Event).join(
        EventRecipient,
        EventRecipient.event_id == Event.id
    ).filter(
        EventRecipient.user_id == user.id,
    ).options(joinedload(Event.project), joinedload(Event.creator)).all()

    # Дедупликация: если событие уже добавлено как "событие проекта"
    seen_event_ids = set()
    if project_ids:
        for e in Event.query.filter(
            Event.event_type == 'project',
            Event.project_id.in_(project_ids)
        ).all():
            seen_event_ids.add(f'event-{e.id}')

    for e in recipient_events:
        if f'event-{e.id}' in seen_event_ids:
            continue  # уже добавлено как событие проекта

        events.append({
            'id': f'recipient-{e.id}',
            'title': f'📅 {e.title}',
            'start': e.start_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': e.end_time.strftime('%Y-%m-%dT%H:%M:%S') if e.end_time else None,
            'allDay': e.all_day,
            'backgroundColor': e.color_hex,
            'borderColor': e.color_hex,
            'textColor': '#ffffff',
            'extendedProps': {
                'type': 'personal',
                'description': e.description or '',
                'project': e.project.name if e.project else '',
                'creator': f"{e.creator.first_name} {e.creator.last_name}" if e.creator else ''
            }
        })

    # ------------------------------------------------
    #  ЗАДАЧИ ПОЛЬЗОВАТЕЛЯ (с дедлайном) — с joinedload
    # ------------------------------------------------
    tasks = Task.query.filter_by(assigned_to=user.id)\
        .filter(Task.due_date.isnot(None))\
        .options(joinedload(Task.project)).all()

    for t in tasks:
        if t.status == 'completed':
            color = '#16a34a'
        elif t.is_overdue:
            color = '#dc2626'
        elif t.status == 'in_progress':
            color = '#f59e0b'
        else:
            color = '#a1a1aa'

        events.append({
            'id': f'task-{t.id}',
            'title': f'📋 {t.title}',
            'start': t.due_date.strftime('%Y-%m-%d'),
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color,
            'textColor': '#ffffff',
            'url': url_for('tasks.view_task', task_id=t.id),
            'extendedProps': {
                'type': 'task',
                'project': t.project.name if t.project else ''
            }
        })

    # ------------------------------------------------
    #  TO-DO ПОЛЬЗОВАТЕЛЯ (с дедлайном) — с joinedload
    # ------------------------------------------------
    todos = Todo.query.filter_by(assigned_to=user.id)\
        .filter(Todo.due_date.isnot(None))\
        .options(joinedload(Todo.project)).all()

    for todo in todos:
        if todo.is_done:
            color = '#16a34a'
        elif todo.is_overdue:
            color = '#dc2626'
        else:
            color = '#0891b2'

        events.append({
            'id': f'todo-{todo.id}',
            'title': f'✅ {todo.title}',
            'start': todo.due_date.strftime('%Y-%m-%d'),
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color,
            'textColor': '#ffffff',
            'url': url_for('projects.view_project', project_id=todo.project_id) + '#todo',
            'extendedProps': {
                'type': 'todo',
                'project': todo.project.name if todo.project else '',
                'done': todo.is_done,
            }
        })

    return jsonify(events)


# ============================================================
#  ЛИЧНЫЕ СОБЫТИЯ
# ============================================================

@bp.route('/personal-event/create', methods=['POST'])
@login_required
def create_personal_event():
    title = request.form['title']
    description = request.form.get('description', '')
    start_str = request.form.get('start_time')
    end_str = request.form.get('end_time')
    all_day = request.form.get('all_day') == 'on'
    color = request.form.get('color', 'blue')

    if not start_str:
        flash('Укажите дату события.', 'warning')
        return redirect(request.referrer or url_for('calendar.my_calendar'))

    if all_day:
        start_time = datetime.strptime(start_str, '%Y-%m-%d')
        end_time = None
    else:
        start_time = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        end_time = None
        if end_str:
            end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')

    event = Event(
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        color=color,
        project_id=None,
        created_by=session['user_id'],
        owner_id=session['user_id'],
        event_type='personal'
    )
    db.session.add(event)
    db.session.commit()

    _log('create_event', event, target_type='event',
         details='Личное событие')

    flash('Личное событие создано!', 'success')
    return redirect(url_for('calendar.my_calendar'))


# ============================================================
#  СОБЫТИЯ ПРОЕКТА (с рассылкой)
# ============================================================

@bp.route('/project/<int:project_id>/event/create', methods=['POST'])
@login_required
def create_event(project_id):
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, project_id):
        flash('Гости не могут создавать события.', 'danger')
        return redirect(url_for('tasks.my_tasks'))

    if not check_full_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    if not can_manage_project(project_id):
        flash('Только руководитель может создавать события проекта.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id) + '#calendar')

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    start_str = request.form.get('start_time')
    end_str = request.form.get('end_time')
    all_day = request.form.get('all_day') == 'on'
    color = request.form.get('color', 'blue')

    if not title:
        flash('Введите название события.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project_id) + '#calendar')

    if not start_str:
        flash('Укажите дату события.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project_id) + '#calendar')

    if all_day:
        start_time = datetime.strptime(start_str, '%Y-%m-%d')
        end_time = None
    else:
        start_time = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        end_time = None
        if end_str:
            end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')

    # Создаём событие
    event = Event(
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        color=color,
        project_id=project_id,
        created_by=session['user_id'],
        event_type='project'
    )
    db.session.add(event)
    db.session.flush()  # чтобы получить event.id

    # Собираем получателей
    recipient_ids = set()

    if request.form.get('notify_all'):
        for m in ProjectMember.query.filter_by(project_id=project_id).all():
            if not m.is_guest and m.user_id != user.id:
                recipient_ids.add(m.user_id)

    if request.form.get('notify_guests'):
        for m in ProjectMember.query.filter_by(project_id=project_id, is_guest=True).all():
            if m.user_id != user.id:
                recipient_ids.add(m.user_id)

    for raw_id in request.form.getlist('recipient_ids'):
        try:
            uid = int(raw_id)
        except ValueError:
            continue
        if uid != user.id:
            recipient_ids.add(uid)

    # Создаём EventRecipient
    for uid in recipient_ids:
        db.session.add(EventRecipient(event_id=event.id, user_id=uid))

    db.session.commit()

    # Логируем
    _log('create_event', event, target_type='event',
         details=f'Проект {project_id}, получателей: {len(recipient_ids)}')

    # Отправляем Push в фоне
    if recipient_ids:
        try:
            from services.push import notify_new_event
            from services.tasks import send_push_async

            push_data_list = notify_new_event(event, recipient_ids, user)
            if push_data_list:
                for pd in push_data_list:
                    send_push_async.delay(**pd)
        except Exception as e:
            print(f'⚠️ Ошибка push события: {e}')

    if recipient_ids:
        flash(f'Событие «{title}» создано. Уведомление отправлено {len(recipient_ids)} получателям.', 'success')
    else:
        flash(f'Событие «{title}» создано.', 'success')

    return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=calendar')


@bp.route('/project/<int:project_id>/events.json')
@login_required
def events_json(project_id):
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, project_id):
        return jsonify([])

    if not check_full_project_access(project_id):
        return jsonify([])

    events = []

    # ------------------------------------------------
    #  СОБЫТИЯ ПРОЕКТА
    # ------------------------------------------------
    for e in Event.query.filter_by(project_id=project_id, event_type='project')\
            .options(joinedload(Event.creator)).all():
        events.append({
            'id': f'event-{e.id}',
            'title': e.title,
            'start': e.start_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': e.end_time.strftime('%Y-%m-%dT%H:%M:%S') if e.end_time else None,
            'allDay': e.all_day,
            'backgroundColor': e.color_hex,
            'borderColor': e.color_hex,
            'textColor': '#ffffff',
            'extendedProps': {
                'type': 'project_event',
                'description': e.description or '',
                'creator': f"{e.creator.first_name} {e.creator.last_name}" if e.creator else ''
            }
        })

    # ------------------------------------------------
    #  ЛИЧНЫЕ СОБЫТИЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ
    # ------------------------------------------------
    for e in Event.query.filter_by(event_type='personal', owner_id=user.id).all():
        events.append({
            'id': f'personal-{e.id}',
            'title': f'👤 {e.title}',
            'start': e.start_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': e.end_time.strftime('%Y-%m-%dT%H:%M:%S') if e.end_time else None,
            'allDay': e.all_day,
            'backgroundColor': e.color_hex,
            'borderColor': e.color_hex,
            'textColor': '#ffffff',
            'extendedProps': {
                'type': 'personal_event',
                'description': e.description or '',
                'creator': 'Личное'
            }
        })

    # ------------------------------------------------
    #  ЗАДАЧИ ПРОЕКТА — с joinedload
    # ------------------------------------------------
    tasks = Task.query.filter_by(project_id=project_id)\
        .filter(Task.due_date.isnot(None))\
        .options(joinedload(Task.assignee)).all()

    for t in tasks:
        if t.status == 'completed':
            color = '#16a34a'
        elif t.is_overdue:
            color = '#dc2626'
        elif t.status == 'in_progress':
            color = '#f59e0b'
        else:
            color = '#a1a1aa'

        events.append({
            'id': f'task-{t.id}',
            'title': f'📋 {t.title}',
            'start': t.due_date.strftime('%Y-%m-%d'),
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color,
            'textColor': '#ffffff',
            'url': url_for('tasks.view_task', task_id=t.id),
            'extendedProps': {
                'type': 'task',
                'assignee': f"{t.assignee.first_name} {t.assignee.last_name}" if t.assignee else 'Не назначена',
                'status': t.status
            }
        })

    # ------------------------------------------------
    #  ВЕХИ ПРОЕКТА
    # ------------------------------------------------
    milestones = Milestone.query.filter_by(project_id=project_id)\
        .filter(Milestone.due_date.isnot(None)).all()

    for m in milestones:
        if m.is_completed:
            color = '#16a34a'
        elif m.is_overdue:
            color = '#dc2626'
        else:
            color = '#8b5cf6'

        events.append({
            'id': f'milestone-{m.id}',
            'title': f'🎯 {m.name}',
            'start': m.due_date.strftime('%Y-%m-%d'),
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color,
            'textColor': '#ffffff',
            'extendedProps': {
                'type': 'milestone',
                'completed': m.is_completed
            }
        })

    # ------------------------------------------------
    #  TO-DO ПРОЕКТА — с joinedload
    # ------------------------------------------------
    todos = Todo.query.filter_by(project_id=project_id)\
        .filter(Todo.due_date.isnot(None))\
        .options(joinedload(Todo.project)).all()

    for todo in todos:
        if todo.is_done:
            color = '#16a34a'
        elif todo.is_overdue:
            color = '#dc2626'
        else:
            color = '#0891b2'

        events.append({
            'id': f'todo-{todo.id}',
            'title': f'✅ {todo.title}',
            'start': todo.due_date.strftime('%Y-%m-%d'),
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color,
            'textColor': '#ffffff',
            'url': url_for('projects.view_project', project_id=project_id) + '#todo',
            'extendedProps': {
                'type': 'todo',
                'done': todo.is_done,
            }
        })

    return jsonify(events)


# ============================================================
#  УДАЛЕНИЕ СОБЫТИЯ
# ============================================================

@bp.route('/event/<int:event_id>/delete', methods=['POST'])
@login_required
def delete_event(event_id):
    e = Event.query.get_or_404(event_id)
    user = User.query.get(session['user_id'])

    if e.event_type == 'personal':
        if e.owner_id != user.id:
            flash('Нет прав.', 'danger')
            return redirect(request.referrer or url_for('dashboard.dashboard'))
        db.session.delete(e)
        db.session.commit()
        flash('Личное событие удалено.', 'info')
        return redirect(url_for('calendar.my_calendar'))
    else:
        if is_project_guest(user.id, e.project_id):
            flash('Гости не могут удалять события.', 'danger')
            return redirect(url_for('tasks.my_tasks'))

        if not can_manage_project(e.project_id) and e.created_by != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('projects.view_project', project_id=e.project_id))

        pid = e.project_id
        db.session.delete(e)
        db.session.commit()
        flash('Событие удалено.', 'info')
        return redirect(url_for('projects.view_project', project_id=pid) + '?_tab=calendar')