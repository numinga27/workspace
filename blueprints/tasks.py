from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from sqlalchemy import select, insert
from sqlalchemy.orm import joinedload

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
    is_privileged,
)
from services.stats import calculate_task_stats
from services.email import send_guest_credentials

bp = Blueprint('tasks', __name__)


# ============================================================
#  ХЕЛПЕР ДЛЯ ЖУРНАЛА
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
#  КЛАСС ДЛЯ ИМИТАЦИИ ПАГИНАЦИИ (для Python-списков)
# ============================================================

class SimplePagination:
    """Имитирует объект пагинации SQLAlchemy для обычных списков."""
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = (total + per_page - 1) // per_page if total > 0 else 1
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1


# ============================================================
#  ОБЩИЙ ХЕЛПЕР ДЛЯ МОИХ ЗАДАЧ И ЗАДАЧ СОТРУДНИКА
# ============================================================

def _build_tasks_context(target_user, current_user, apply_pagination=False):
    """Собирает контекст для шаблонов my_tasks.html и user_all_tasks.html.
    
    apply_pagination=True — включает пагинацию (для my_tasks).
    """
    # 1. Загружаем ВСЕ задачи пользователя (с joinedload для N+1)
    all_tasks = Task.query.filter_by(assigned_to=target_user.id)\
        .options(joinedload(Task.project), joinedload(Task.assignee))\
        .order_by(Task.due_date.asc().nullslast(), Task.status).all()

    # 2. Считаем статистику по ПОЛНОМУ списку (для бейджиков и вкладок)
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

    todos = Todo.query.filter_by(assigned_to=target_user.id, is_done=False)\
        .order_by(Todo.created_at.desc()).all()

    # 3. Применяем фильтры (проект, статус) к полному списку
    filter_project = request.args.get('project', '')
    filter_status = request.args.get('status', '')

    filtered_tasks = all_tasks
    if filter_project:
        filtered_tasks = [t for t in filtered_tasks if str(t.project_id) == filter_project]
    if filter_status:
        filtered_tasks = [t for t in filtered_tasks if t.status == filter_status]

    # 4. ПАГИНАЦИЯ (только если включена)
    pagination = None
    if apply_pagination:
        page = request.args.get('page', 1, type=int)
        per_page = 20  # ← Можно менять: 10, 20, 50
        
        total = len(filtered_tasks)
        start = (page - 1) * per_page
        end = start + per_page
        tasks_page = filtered_tasks[start:end]
        
        pagination = SimplePagination(tasks_page, page, per_page, total)
        tasks_to_show = tasks_page
    else:
        tasks_to_show = filtered_tasks

    # 5. Проекты для сайдбара
    if target_user.id == current_user.id:
        projects = get_user_projects(current_user)
    else:
        projects = [m.project for m in target_user.projects if not m.is_guest]

    is_guest_user = any(m.is_guest for m in target_user.projects)

    return {
        'all_tasks': all_tasks,
        'active': active,
        'overdue': overdue,
        'completed': completed,
        'urgent': urgent,
        'todos': todos,
        'tasks': tasks_to_show,
        'pagination': pagination,
        'projects': projects,
        'filter_project': filter_project,
        'filter_status': filter_status,
        'now': now,
        'is_guest_user': is_guest_user,
    }


# ============================================================
#  МОИ ЗАДАЧИ
# ============================================================

@bp.route('/my-tasks')
@login_required
def my_tasks():
    user = db.session.get(User, session['user_id'])
    
    # ← Включаем пагинацию для своих задач
    ctx = _build_tasks_context(target_user=user, current_user=user, apply_pagination=True)
    
    unread_task_ids = get_unread_task_ids(user.id)
    unread_todo_ids = get_unread_todo_ids(user.id)

    return render_template('my_tasks.html',
                           user=user,
                           tasks=ctx['tasks'],
                           pagination=ctx['pagination'],
                           active=ctx['active'],
                           overdue=ctx['overdue'],
                           completed=ctx['completed'],
                           urgent=ctx['urgent'],
                           my_todos=ctx['todos'],
                           projects=ctx['projects'],
                           filter_project=ctx['filter_project'],
                           filter_status=ctx['filter_status'],
                           now=ctx['now'],
                           is_guest_user=ctx['is_guest_user'],
                           unread_task_ids=unread_task_ids,
                           unread_todo_ids=unread_todo_ids)


# ============================================================
#  ОТМЕТИТЬ ВСЁ ПРОЧИТАННЫМ
# ============================================================

@bp.route('/my-tasks/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    user = db.session.get(User, session['user_id'])
    user_id = user.id

    # 1. Находим ID задач, которые назначены юзеру, но еще не отмечены как прочитанные
    read_tasks_subquery = select(TaskRead.task_id).where(TaskRead.user_id == user_id)
    unread_tasks_query = db.session.query(Task.id).filter(
        Task.assigned_to == user_id,
        ~Task.id.in_(read_tasks_subquery)
    ).all()
    unread_task_ids = [tid for (tid,) in unread_tasks_query]

    # 2. То же самое для To-Do
    read_todos_subquery = select(TodoRead.todo_id).where(TodoRead.user_id == user_id)
    unread_todos_query = db.session.query(Todo.id).filter(
        Todo.assigned_to == user_id,
        ~Todo.id.in_(read_todos_subquery)
    ).all()
    unread_todo_ids = [tid for (tid,) in unread_todos_query]

    # 3. Массовая вставка (INSERT ... VALUES)
    if unread_task_ids:
        db.session.execute(
            insert(TaskRead),
            [{'user_id': user_id, 'task_id': tid} for tid in unread_task_ids]
        )
    
    if unread_todo_ids:
        db.session.execute(
            insert(TodoRead),
            [{'user_id': user_id, 'todo_id': tid} for tid in unread_todo_ids]
        )

    db.session.commit()

    total = len(unread_task_ids) + len(unread_todo_ids)
    if total > 0:
        flash(f'Отмечено как прочитанное: {total}.', 'success')
    else:
        flash('Все уже прочитано.', 'info')

    return redirect(url_for('tasks.my_tasks'))


# ============================================================
#  ВСЕ ЗАДАЧИ СОТРУДНИКА
# ============================================================

@bp.route('/user/<int:user_id>/all-tasks')
@login_required
def user_all_tasks(user_id):
    current_user = db.session.get(User, session['user_id'])
    employee = db.session.get(User, user_id)

    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    # Проверка прав
    is_allowed = False
    if is_privileged(current_user):
        is_allowed = True
    else:
        employee_projects = [m.project_id for m in employee.projects if not m.is_guest]
        managed_projects = []
        for m in current_user.projects:
            if not m.is_guest and m.is_manager:
                managed_projects.append(m.project_id)
        if set(employee_projects) & set(managed_projects):
            is_allowed = True

    if not is_allowed:
        flash('У вас нет прав.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    # ← Для чужих задач пагинацию пока не включаем
    ctx = _build_tasks_context(target_user=employee, current_user=current_user, apply_pagination=False)

    return render_template('user_all_tasks.html',
                           employee=employee,
                           tasks=ctx['tasks'],
                           active=ctx['active'],
                           overdue=ctx['overdue'],
                           completed=ctx['completed'],
                           urgent=ctx['urgent'],
                           employee_todos=ctx['todos'],
                           employee_projects=ctx['projects'],
                           filter_project=ctx['filter_project'],
                           filter_status=ctx['filter_status'],
                           now=ctx['now'],
                           user=current_user,
                           projects=get_user_projects(current_user))


# ============================================================
#  ПРОСМОТР ЗАДАЧИ
# ============================================================

@bp.route('/task/<int:task_id>')
@login_required
def view_task(task_id):
    task = Task.query.get_or_404(task_id)
    user = db.session.get(User, session['user_id'])

    if task.assigned_to == user.id:
        mark_task_as_read(user.id, task.id)

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

    if not check_full_project_access(task.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    user_role = get_user_role_in_project(task.project_id)

    files = File.query.filter_by(task_id=task.id).all()
    # ← joinedload для подзадач
    subtasks = Task.query.filter_by(parent_task_id=task.id)\
        .options(joinedload(Task.assignee))\
        .all()
    all_users = User.query.filter(User.role != 'admin').all()
    milestones = Milestone.query.filter_by(project_id=task.project_id).all()

    task_stats = calculate_task_stats(task)

    project = task.project
    contact_persons = []
    if project.customer:
        contact_persons.extend(project.customer.contacts)
    if project.supplier:
        contact_persons.extend(project.supplier.contacts)
    for sub in project.subcontractors:
        contact_persons.extend(sub.contacts)

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
    user = db.session.get(User, session['user_id'])

    if is_project_guest(user.id, task.project_id):
        flash('Гости не могут редактировать задачи.', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    if not can_manage_project(task.project_id) and task.assigned_to != user.id:
        flash('Нет прав.', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    old_title = task.title
    old_status = task.status
    old_assigned = task.assigned_to

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
            # ← ИСПРАВЛЕНО: проверка через связь subcontractors
            if contact.supplier_id and any(s.id == contact.supplier_id for s in project.subcontractors):
                belongs = True

            if not belongs:
                flash('Это контактное лицо не связано с проектом.', 'danger')
                return redirect(url_for('tasks.view_task', task_id=task_id))

            guest_user, plain_password = get_or_create_guest_user(contact)
            add_guest_to_project(guest_user.id, task.project_id, session['user_id'])
            task.assigned_to = guest_user.id

            if plain_password:
                send_guest_credentials(
                    recipient=guest_user,
                    plain_password=plain_password,
                    project=task.project,
                    inviter=user,
                )
    else:
        task.assigned_to = None

    milestone_id = request.form.get('milestone_id')
    if milestone_id:
        ms = _validate_milestone_in_project(int(milestone_id), task.project_id)
        task.milestone_id = ms.id if ms else None
    else:
        task.milestone_id = None

    db.session.commit()

    # ← Логируем изменение
    changes = []
    if old_title != task.title:
        changes.append(f'«{old_title}» → «{task.title}»')
    if old_status != task.status:
        changes.append(f'статус: {old_status} → {task.status}')
    if old_assigned != task.assigned_to:
        changes.append('сменён исполнитель')

    details = '; '.join(changes) if changes else None
    _log('edit_task', task, target_type='task', details=details)

    flash('Задача обновлена!', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ============================================================
#  КОММЕНТАРИЙ К ЗАДАЧЕ
# ============================================================

@bp.route('/task/<int:task_id>/comment', methods=['POST'])
@login_required
def update_task_comment(task_id):
    task = Task.query.get_or_404(task_id)
    user = db.session.get(User, session['user_id'])

    if is_project_guest(user.id, task.project_id):
        if task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.my_tasks'))
    else:
        if not check_full_project_access(task.project_id):
            flash('Нет доступа.', 'danger')
            return redirect(url_for('dashboard.dashboard'))

        member = ProjectMember.query.filter_by(
            user_id=user.id, project_id=task.project_id
        ).first()
        if (not member or not member.is_manager) and not is_privileged(user) \
                and task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.view_task', task_id=task_id))

    task.comment = request.form.get('comment', '')
    db.session.commit()

    _log('edit_task', task, target_type='task',
         details='Изменён комментарий')

    flash('Комментарий сохранён.', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


# ============================================================
#  СМЕНА СТАТУСА
# ============================================================

@bp.route('/task/<int:task_id>/update_status', methods=['POST'])
@login_required
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    user = db.session.get(User, session['user_id'])

    if is_project_guest(user.id, task.project_id):
        if task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('tasks.my_tasks'))
    else:
        if not can_manage_project(task.project_id) and task.assigned_to != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('projects.view_project', project_id=task.project_id))

    old_status = task.status
    task.status = request.form['status']
    db.session.commit()

    # ← Логируем смену статуса
    if old_status != task.status:
        _log('edit_task', task, target_type='task',
             details=f'Статус: {old_status} → {task.status}')

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
    user = db.session.get(User, session['user_id'])

    if is_project_guest(user.id, pid):
        flash('Гости не могут удалять задачи.', 'danger')
        return redirect(url_for('tasks.view_task', task_id=task_id))

    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid))

    # ← Логируем удаление ДО физического
    _log('delete_task', task, target_type='task',
         details=f'Удалена задача «{task.title}»')

    for st in task.subtasks:
        db.session.delete(st)
    db.session.delete(task)
    db.session.commit()
    flash('Задача удалена.', 'info')
    return redirect(url_for('projects.view_project', project_id=pid))


# ============================================================
#  ЗАДАЧА ОТ АДМИНИСТРАТОРА / СУПЕРВИЗОРА
# ============================================================

@bp.route('/project/<int:project_id>/admin-assign-task', methods=['POST'])
@login_required
def admin_assign_task(project_id):
    """Админ или супервизор ставит задачу руководителю ИЛИ любому участнику."""
    user = db.session.get(User, session['user_id'])
    if not user or not is_privileged(user):
        flash('Только администратор или супервизор может ставить задачи от своего имени.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    assigned_raw = request.form.get('assigned_to', '')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    due_str = request.form.get('due_date')
    allow_any = request.form.get('allow_any') == '1'

    if not assigned_raw or not title:
        flash('Заполните исполнителя и название задачи.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

    if ':' in assigned_raw:
        kind, raw_id = assigned_raw.split(':', 1)
    else:
        kind, raw_id = 'user', assigned_raw

    assigned_user_id = None

    if kind == 'user':
        try:
            assigned_user_id = int(raw_id)
        except ValueError:
            flash('Некорректный исполнитель.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

        member = ProjectMember.query.filter_by(
            user_id=assigned_user_id,
            project_id=project_id,
        ).first()

        if not member:
            flash('Исполнитель не является участником проекта.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

        if not allow_any and not member.is_manager:
            flash('Исполнитель должен быть руководителем или менеджером проекта.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

    elif kind == 'contact':
        try:
            contact_id = int(raw_id)
        except ValueError:
            flash('Некорректное контактное лицо.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

        contact = ContactPerson.query.get(contact_id)
        if not contact:
            flash('Контактное лицо не найдено.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

        project = db.session.get(Project, project_id)
        belongs = False
        if contact.customer_id and project.customer_id == contact.customer_id:
            belongs = True
        if contact.supplier_id and project.supplier_id == contact.supplier_id:
            belongs = True
        if contact.supplier_id:
            sub_ids = {s.id for s in project.subcontractors}
            if contact.supplier_id in sub_ids:
                belongs = True

        if not belongs:
            flash('Это контактное лицо не связано с проектом.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

        guest_user, plain_password = get_or_create_guest_user(contact)
        add_guest_to_project(guest_user.id, project_id, session['user_id'])
        assigned_user_id = guest_user.id

        if plain_password:
            send_guest_credentials(
                recipient=guest_user,
                plain_password=plain_password,
                project=project,
                inviter=user,
            )

    else:
        flash('Некорректный тип исполнителя.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id) + '?_tab=tasks')

    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(due_str, '%Y-%m-%d')
        except ValueError:
            pass

    task = Task(
        title=title,
        description=description,
        project_id=project_id,
        assigned_to=assigned_user_id,
        created_by=user.id,
        due_date=due_date,
        source='admin' if user.is_admin else 'supervisor',
        supervisor_id=user.id,
    )
    db.session.add(task)
    db.session.commit()

    # ← Логирование от админа/супервизора НЕ делаем — админов journal игнорирует

    # ← Push
    try:
        from services.push import notify_new_task
        notify_new_task(task, user)
    except Exception as e:
        print(f'⚠️ Ошибка push: {e}')

    assignee = db.session.get(User, assigned_user_id)
    assignee_name = (
        f'{assignee.first_name} {assignee.last_name}' if assignee else 'исполнителя'
    )
    role_label = 'администратора' if user.is_admin else 'супервизора'
    flash(f'Задача «{title}» от {role_label} поставлена — {assignee_name}.', 'success')

    return redirect(url_for('projects.view_project', project_id=project_id)
                    + f'?_tab=tasks&created={task.id}')