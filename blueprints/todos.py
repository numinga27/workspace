from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import Todo, User, Project, Task
from decorators import login_required
from utils import (
    utcnow, check_project_access, check_full_project_access,
    can_manage_project, is_project_guest,
    _validate_project_member,
    # ← НОВОЕ: для уведомлений
    mark_todo_as_read,
)

bp = Blueprint('todos', __name__)


# ============================================================
#  СОЗДАНИЕ TO-DO
# ============================================================

@bp.route('/project/<int:project_id>/todo/create', methods=['POST'])
@login_required
def create_todo(project_id):
    user = User.query.get(session['user_id'])

    # Гость не может создавать To-Do
    if is_project_guest(user.id, project_id):
        flash('Гости не могут создавать To-Do.', 'danger')
        return redirect(url_for('tasks.my_tasks'))

    if not check_full_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    assigned = request.form.get('assigned_to')
    due_str = request.form.get('due_date')
    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(due_str, '%Y-%m-%d')
        except ValueError:
            pass

    # Валидация исполнителя
    assigned_to_id = None
    if assigned:
        member = _validate_project_member(project_id, int(assigned))
        if not member or member.is_guest:
            flash('Выбранный исполнитель не является участником проекта.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=todo')
        assigned_to_id = member.user_id

    todo = Todo(
        title=request.form['title'],
        project_id=project_id,
        assigned_to=assigned_to_id,
        created_by=session['user_id'],
        due_date=due_date
    )
    db.session.add(todo)
    db.session.commit()
    flash('Задача добавлена в To-Do!', 'success')

    # Редирект с ID нового To-Do для подсветки
    return redirect(url_for('projects.view_project', project_id=project_id)
                    + f'?_tab=todo&created_todo={todo.id}')


# ============================================================
#  ПЕРЕКЛЮЧЕНИЕ СТАТУСА
# ============================================================

@bp.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    t = Todo.query.get_or_404(todo_id)
    user = User.query.get(session['user_id'])

    # Гость может менять статус только своих To-Do
    if is_project_guest(user.id, t.project_id):
        if t.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.my_tasks'))
    elif not check_full_project_access(t.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    # ← НОВОЕ: если To-Do назначено на текущего пользователя — отметить прочитанным
    if t.assigned_to == user.id:
        mark_todo_as_read(user.id, t.id)

    t.is_done = not t.is_done
    t.done_at = utcnow() if t.is_done else None
    db.session.commit()

    return redirect(request.referrer or url_for('projects.view_project', project_id=t.project_id) + '?_tab=todo')


# ============================================================
#  КОММЕНТАРИЙ К TO-DO
# ============================================================

@bp.route('/todo/<int:todo_id>/comment', methods=['POST'])
@login_required
def update_todo_comment(todo_id):
    t = Todo.query.get_or_404(todo_id)
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, t.project_id):
        if t.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.my_tasks'))
    elif not check_full_project_access(t.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    t.comment = request.form.get('comment', '')
    db.session.commit()
    flash('Комментарий сохранён.', 'success')
    return redirect(request.referrer or url_for('projects.view_project', project_id=t.project_id) + '?_tab=todo')


# ============================================================
#  РЕДАКТИРОВАНИЕ TO-DO
# ============================================================

@bp.route('/todo/<int:todo_id>/edit', methods=['POST'])
@login_required
def edit_todo(todo_id):
    """Редактирование существующего To-Do.
    Может: руководитель/менеджер проекта, создатель To-Do, назначенный исполнитель.
    Гость не может."""
    t = Todo.query.get_or_404(todo_id)
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, t.project_id):
        flash('Гости не могут редактировать To-Do.', 'danger')
        return redirect(url_for('tasks.my_tasks'))

    if not check_full_project_access(t.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    if (not can_manage_project(t.project_id)
            and t.created_by != user.id
            and t.assigned_to != user.id):
        flash('Нет прав на редактирование этого To-Do.', 'danger')
        return redirect(url_for('projects.view_project', project_id=t.project_id) + '?_tab=todo')

    # ← НОВОЕ: если To-Do назначено на текущего пользователя — отметить прочитанным
    if t.assigned_to == user.id:
        mark_todo_as_read(user.id, t.id)

    # Обновляем поля
    t.title = request.form.get('title', t.title).strip() or t.title
    t.comment = request.form.get('comment', '').strip() or None

    due = request.form.get('due_date')
    if due:
        try:
            t.due_date = datetime.strptime(due, '%Y-%m-%d')
        except ValueError:
            t.due_date = None
    else:
        t.due_date = None

    assigned = request.form.get('assigned_to')
    if assigned:
        member = _validate_project_member(t.project_id, int(assigned))
        if member and not member.is_guest:
            t.assigned_to = member.user_id
        else:
            t.assigned_to = None
    else:
        t.assigned_to = None

    db.session.commit()
    flash('To-Do обновлён.', 'success')
    return redirect(url_for('projects.view_project', project_id=t.project_id) + '?_tab=todo')


# ============================================================
#  УДАЛЕНИЕ TO-DO
# ============================================================

@bp.route('/todo/<int:todo_id>/delete', methods=['POST'])
@login_required
def delete_todo(todo_id):
    t = Todo.query.get_or_404(todo_id)
    pid = t.project_id
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, pid):
        flash('Гости не могут удалять To-Do.', 'danger')
        return redirect(url_for('tasks.my_tasks'))

    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid) + '?_tab=todo')

    db.session.delete(t)
    db.session.commit()
    flash('To-Do удалён.', 'info')
    return redirect(url_for('projects.view_project', project_id=pid) + '?_tab=todo')