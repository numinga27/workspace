from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import (
    User, Task, Todo, File, Milestone, Project, ContactPerson, ProjectMember,
    TaskRead, TodoRead,
)
from decorators import login_required
from utils import (
    utcnow, check_project_access, check_full_project_access,
    get_user_role_in_project, can_manage_project, get_user_projects,
    is_project_guest, mark_project_as_read,
    _validate_project_member, _validate_task_in_project,
    _validate_milestone_in_project,
    get_or_create_guest_user, add_guest_to_project,
    get_unread_task_ids, get_unread_todo_ids,
    mark_task_as_read, mark_todo_as_read,
)
from services.stats import calculate_task_stats

bp = Blueprint('tasks', __name__)


# ============================================================
#  МОИ ЗАДАЧИ
# ============================================================

@bp.route('/my-tasks')
@login_required
def my_tasks():
    user = User.query.get(session['user_id'])

    all_my_tasks = Task.query.filter_by(assigned_to=user.id)\
        .order_by(Task.due_date.asc().nullslast(), Task.status).all()

    active = [t for t in all_my_tasks if t.status in ('new', 'in_progress')]
    overdue = [t for t in all_my_tasks if t.is_overdue]
    completed = [t for t in all_my_tasks if t.status == 'completed']

    now = utcnow()
    urgent = []
    for t in active:
        if t.due_date:
            days_left = (t.due_date - now).days
            if 0 <= days_left <= 3:
                urgent.append(t)

    my_todos = Todo.query.filter_by(assigned_to=user.id, is_done=False)\
        .order_by(Todo.created_at.desc()).all()

    filter_project = request.args.get('project', '')
    filter_status = request.args.get('status', '')

    tasks = all_my_tasks
    if filter_project:
        tasks = [t for t in tasks if str(t.project_id) == filter_project]
    if filter_status:
        tasks = [t for t in tasks if t.status == filter_status]

    projects = get_user_projects(user)

    is_guest_user = False
    for m in user.projects:
        if m.is_guest:
            is_guest_user = True
            break

    unread_task_ids = get_unread_task_ids(user.id)
    unread_todo_ids = get_unread_todo_ids(user.id)

    return render_template('my_tasks.html',
                           user=user,
                           tasks=tasks,
                           active=active,
                           overdue=overdue,
                           completed=completed,
                           urgent=urgent,
                           my_todos=my_todos,
                           projects=projects,
                           filter_project=filter_project,
                           filter_status=filter_status,
                           now=now,
                           is_guest_user=is_guest_user,
                           unread_task_ids=unread_task_ids,
                           unread_todo_ids=unread_todo_ids)


# ============================================================
#  ОТМЕТИТЬ ВСЁ ПРОЧИТАННЫМ
# ============================================================

@bp.route('/my-tasks/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    """Отмечает все задачи и To-Do текущего пользователя прочитанными."""
    user = User.query.get(session['user_id'])

    # --- Задачи ---
    my_task_ids = {t.id for t in Task.query.filter_by(assigned_to=user.id).all()}
    already_read_task_ids = {r.task_id for r in TaskRead.query.filter_by(user_id=user.id).all()}
    unread_task_ids = my_task_ids - already_read_task_ids

    for task_id in unread_task_ids:
        db.session.add(TaskRead(user_id=user.id, task_id=task_id))

    # --- To-Do ---
    my_todo_ids = {t.id for t in Todo.query.filter_by(assigned_to=user.id).all()}
    already_read_todo_ids = {r.todo_id for r in TodoRead.query.filter_by(user_id=user.id).all()}
    unread_todo_ids = my_todo_ids - already_read_todo_ids

    for todo_id in unread_todo_ids:
        db.session.add(TodoRead(user_id=user.id, todo_id=todo_id))

    db.session.commit()

    total = len(unread_task_ids) + len(unread_todo_ids)
    if total > 0:
        flash(f'Отмечено как прочитанное: {total}.', 'success')
    else:
        flash('Все уже прочитано.', 'info')

    return redirect(url_for('tasks.my_tasks'))


# ============================================================
#  ВСЕ ЗАДАЧИ СОТРУДНИКА (для руководителей)
# ============================================================

@bp.route('/user/<int:user_id>/all-tasks')
@login_required
def user_all_tasks(user_id):
    current_user = User.query.get(session['user_id'])
    employee = User.query.get(user_id)

    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    is_allowed = False
    if current_user.role == 'admin':
        is_allowed = True
    else:
        employee_projects = [m.project_id for m in employee.projects if not m.is_guest]
        managed_projects = []
        for m in current_user.projects:
            if not m.is_guest and m.role_in_project in ('admin', 'manager'):
                managed_projects.append(m.project_id)
        if set(employee_projects) & set(managed_projects):
            is_allowed = True

    if not is_allowed:
        flash('У вас нет прав.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    all_tasks = Task.query.filter_by(assigned_to=user_id)\
        .order_by(Task.due_date.asc().nullslast(), Task.status).all()

    active = [t for t in all_tasks if t.status in ('new', 'in_progress')]
    overdue = [t for t in all_tasks if t.is_overdue]
    completed = [t for t in all_tasks if t.status == 'completed']

    now = utcnow()
    urgent = []
    for t in active:
        if t.due_date:
            days_left = (t.due_date - now).days
            if 0 <= days_left <= 3:
                urgent.append(t)

    employee_todos = Todo.query.filter_by(assigned_to=user_id, is_done=False)\
        .order_by(Todo.created_at.desc()).all()

    filter_project = request.args.get('project', '')
    filter_status = request.args.get('status', '')

    tasks = all_tasks
    if filter_project:
        tasks = [t for t in tasks if str(t.project_id) == filter_project]
    if filter_status:
        tasks = [t for t in tasks if t.status == filter_status]

    employee_projects = []
    for m in employee.projects:
        if not m.is_guest:
            employee_projects.append(m.project)

    return render_template('user_all_tasks.html',
                           employee=employee,
                           tasks=tasks,
                           active=active,
                           overdue=overdue,
                           completed=completed,
                           urgent=urgent,
                           employee_todos=employee_todos,
                           employee_projects=employee_projects,
                           filter_project=filter_project,
                           filter_status=filter_status,
                           now=now,
                           user=current_user,
                           projects=get_user_projects(current_user))


# ============================================================
#  ПРОСМОТР ЗАДАЧИ
# ============================================================

@bp.route('/task/<int:task_id>')
@login_required
def view_task(task_id):
    task = Task.query.get_or_404(task_id)
    user = User.query.get(session['user_id'])

    # Если задача назначена на текущего пользователя — отметить прочитанной
    if task.assigned_to == user.id:
        mark_task_as_read(user.id, task.id)

    # --- ГОСТЬ ---
    if is_project_guest(user.id, task.project_id):
        if task.assigned_to != user.id:
            flash('У вас нет доступа к этой задаче.', 'danger')
            return redirect(url_for('tasks.my_tasks'))

        return render_template('task_detail.html',
                               task=task,
                               project=task.project,
                               files=File.query.filter_by(task_id=task.id).all(),
                               subtasks=[],
                               all_users=[],
                               milestones=[],
                               contact_persons=[],
                               user=user,
                               user_role='guest',
                               now=utcnow(),
                               projects=[],
                               can_manage=False,
                               task_stats=calculate_task_stats(task),
                               is_guest_view=True)

    # --- ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ / РУКОВОДИТЕЛЬ ---
    if not check_full_project_access(task.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    user_role = get_user_role_in_project(task.project_id)

    files = File.query.filter_by(task_id=task.id).all()
    subtasks = Task.query.filter_by(parent_task_id=task.id).all()
    all_users = User.query.filter(User.role != 'admin').all()
    milestones = Milestone.query.filter_by(project_id=task.project_id).all()

    task_stats = calculate_task_stats(task)

    project = task.project
    contact_persons = []
    if project.customer:
        contact_persons.extend(project.customer.contacts)
    if project.supplier:
        contact_persons.extend(project.supplier.contacts)
    if project.subcontractor:
        contact_persons.extend(project.subcontractor.contacts)

    return render_template('task_detail.html',
                           task=task,
                           project=project,
                           files=files,
                           subtasks=subtasks,
                           all_users=all_users,
                           milestones=milestones,
                           contact_persons=contact_persons,
                           user=user,
                           user_role=user_role,
                           now=utcnow(),
                           projects=get_user_projects(user),
                           can_manage=can_manage_project(task.project_id),
                           task_stats=task_stats,
                           is_guest_view=False)


# ============================================================
#  РЕДАКТИРОВАНИЕ ЗАДАЧИ
# ============================================================

@bp.route('/task/<int:task_id>/edit', methods=['POST'])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, task.project_id):
        flash('Гости не могут редактировать задачи.', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    if not can_manage_project(task.project_id) and task.assigned_to != user.id:
        flash('Нет прав.', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    task.title = request.form['title']
    task.description = request.form.get('description', '')
    task.status = request.form.get('status', task.status)

    due = request.form.get('due_date')
    task.due_date = datetime.strptime(due, '%Y-%m-%d') if due else None

    assigned = request.form.get('assigned_to')
    if assigned:
        if ':' in assigned:
            kind, raw_id = assigned.split(':', 1)
        else:
            kind, raw_id = 'user', assigned

        try:
            value_id = int(raw_id)
        except ValueError:
            flash('Некорректный исполнитель.', 'danger')
            return redirect(url_for('tasks.view_task', task_id=task_id))

        if kind == 'user':
            member = _validate_project_member(task.project_id, value_id)
            if not member or member.is_guest:
                flash('Недопустимый исполнитель.', 'danger')
                return redirect(url_for('tasks.view_task', task_id=task_id))
            task.assigned_to = member.user_id

        elif kind == 'contact':
            contact = ContactPerson.query.get(value_id)
            if not contact:
                flash('Контактное лицо не найдено.', 'danger')
                return redirect(url_for('tasks.view_task', task_id=task_id))

            project = task.project
            belongs = False
            if contact.customer_id and project.customer_id == contact.customer_id:
                belongs = True
            if contact.supplier_id and project.supplier_id == contact.supplier_id:
                belongs = True
            if contact.supplier_id and project.subcontractor_id == contact.supplier_id:
                belongs = True

            if not belongs:
                flash('Это контактное лицо не связано с проектом.', 'danger')
                return redirect(url_for('tasks.view_task', task_id=task_id))

            guest_user = get_or_create_guest_user(contact)
            add_guest_to_project(guest_user.id, task.project_id, session['user_id'])
            task.assigned_to = guest_user.id
    else:
        task.assigned_to = None

    milestone_id = request.form.get('milestone_id')
    if milestone_id:
        ms = _validate_milestone_in_project(int(milestone_id), task.project_id)
        task.milestone_id = ms.id if ms else None
    else:
        task.milestone_id = None

    db.session.commit()
    flash('Задача обновлена!', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ============================================================
#  КОММЕНТАРИЙ К ЗАДАЧЕ
# ============================================================

@bp.route('/task/<int:task_id>/comment', methods=['POST'])
@login_required
def update_task_comment(task_id):
    task = Task.query.get_or_404(task_id)
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, task.project_id):
        if task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.my_tasks'))
    else:
        if not check_full_project_access(task.project_id):
            flash('Нет доступа.', 'danger')
            return redirect(url_for('dashboard.dashboard'))

        role = get_user_role_in_project(task.project_id)
        if role not in ['admin', 'manager'] and task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.view_task', task_id=task_id))

    task.comment = request.form.get('comment', '')
    db.session.commit()
    flash('Комментарий сохранён.', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ============================================================
#  СМЕНА СТАТУСА
# ============================================================

@bp.route('/task/<int:task_id>/update_status', methods=['POST'])
@login_required
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, task.project_id):
        if task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.my_tasks'))
    else:
        if not can_manage_project(task.project_id) and task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('projects.view_project', project_id=task.project_id))

    task.status = request.form['status']
    db.session.commit()
    flash('Статус обновлён!', 'success')
    return redirect(request.referrer or url_for('projects.view_project', project_id=task.project_id))


# ============================================================
#  УДАЛЕНИЕ ЗАДАЧИ
# ============================================================

@bp.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    pid = task.project_id
    user = User.query.get(session['user_id'])

    if is_project_guest(user.id, pid):
        flash('Гости не могут удалять задачи.', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid))

    for st in task.subtasks:
        db.session.delete(st)
    db.session.delete(task)
    db.session.commit()
    flash('Задача удалена.', 'info')
    return redirect(url_for('projects.view_project', project_id=pid))