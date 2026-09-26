from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import (
    User, Project, ProjectMember, Task, Milestone, Message, Folder, File,
    Todo, Report, Event, Supplier, ContactPerson
)
from decorators import login_required
from utils import (
    utcnow, check_project_access, check_full_project_access, get_user_role_in_project,
    can_manage_project, get_user_projects, get_available_customers, get_available_suppliers,
    mark_project_as_read, is_project_guest,
    get_or_create_guest_user, add_guest_to_project,
    _validate_project_member, _validate_task_in_project, _validate_milestone_in_project,
)
from services.stats import get_todo_stats

bp = Blueprint('projects', __name__)


# ============================================================
#  ХЕЛПЕРЫ
# ============================================================

def _split_suppliers_by_type(user):
    """Возвращает два списка: обычные поставщики и субподрядчики."""
    all_suppliers = get_available_suppliers(user)
    suppliers = [s for s in all_suppliers if s.supplier_type == 'supplier']
    subcontractors = [s for s in all_suppliers if s.supplier_type == 'subcontractor']
    return suppliers, subcontractors


# ============================================================
#  СОЗДАНИЕ ПРОЕКТА
# ============================================================

@bp.route('/project/create', methods=['GET', 'POST'])
@login_required
def create_project():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        start_date = None
        if request.form.get('start_date'):
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')

        end_date = None
        if request.form.get('end_date'):
            end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')

        customer_id = request.form.get('customer_id') or None
        supplier_id = request.form.get('supplier_id') or None
        subcontractor_id = request.form.get('subcontractor_id') or None

        project = Project(
            name=request.form['name'],
            description=request.form['description'],
            created_by=session['user_id'],
            customer_id=int(customer_id) if customer_id else None,
            supplier_id=int(supplier_id) if supplier_id else None,
            subcontractor_id=int(subcontractor_id) if subcontractor_id else None,
            start_date=start_date or utcnow(),
            end_date=end_date,
        )
        db.session.add(project)
        db.session.commit()

        db.session.add(ProjectMember(
            user_id=session['user_id'],
            project_id=project.id,
            role_in_project='admin',
            is_guest=False,
        ))
        db.session.commit()

        flash('Проект создан! Вы назначены руководителем.', 'success')
        return redirect(url_for('projects.view_project', project_id=project.id))

    # --- GET ---
    suppliers, subcontractors = _split_suppliers_by_type(user)

    return render_template('create_project.html',
                           customers=get_available_customers(user),
                           suppliers=suppliers,
                           subcontractors=subcontractors,
                           user=user,
                           projects=get_user_projects(user))


# ============================================================
#  ПРОСМОТР ПРОЕКТА
# ============================================================

@bp.route('/project/<int:project_id>')
@login_required
def view_project(project_id):
    user = User.query.get(session['user_id'])

    # Гости не видят проект целиком — редирект на свои задачи
    if is_project_guest(user.id, project_id):
        flash('Вы — гость проекта. Вам доступны только ваши задачи.', 'info')
        return redirect(url_for('tasks.my_tasks'))

    if not check_full_project_access(project_id):
        flash('У вас нет доступа к этому проекту.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    project = Project.query.get_or_404(project_id)

    if request.args.get('mark_read') == '1':
        mark_project_as_read(user.id, project_id)

    members_all = ProjectMember.query.filter_by(project_id=project.id).all()
    members = [m for m in members_all if not m.is_guest]

    # ------------------------------------------------
    #  ФИЛЬТРЫ ЗАДАЧ
    # ------------------------------------------------
    filter_assignee = request.args.get('filter_assignee', '')
    filter_status = request.args.get('filter_status', '')
    filter_due_from = request.args.get('filter_due_from', '')
    filter_due_to = request.args.get('filter_due_to', '')

    tasks_all = Task.query.filter_by(project_id=project.id, parent_task_id=None).all()
    tasks = list(tasks_all)

    if filter_assignee:
        if filter_assignee == 'unassigned':
            tasks = [t for t in tasks if not t.assigned_to]
        else:
            try:
                target_id = int(filter_assignee)
                tasks = [t for t in tasks if t.assigned_to == target_id]
            except ValueError:
                pass

    if filter_status:
        if filter_status == 'overdue':
            tasks = [t for t in tasks if t.is_overdue]
        else:
            tasks = [t for t in tasks if t.status == filter_status]

    if filter_due_from:
        try:
            d = datetime.strptime(filter_due_from, '%Y-%m-%d')
            tasks = [t for t in tasks if t.due_date and t.due_date >= d]
        except ValueError:
            pass

    if filter_due_to:
        try:
            d = datetime.strptime(filter_due_to, '%Y-%m-%d')
            tasks = [t for t in tasks if t.due_date and t.due_date <= d]
        except ValueError:
            pass

    # ------------------------------------------------
    #  ФИЛЬТРЫ TO-DO
    # ------------------------------------------------
    todo_filter_assignee = request.args.get('todo_filter_assignee', '')
    todo_filter_status = request.args.get('todo_filter_status', '')
    todo_filter_due_from = request.args.get('todo_filter_due_from', '')
    todo_filter_due_to = request.args.get('todo_filter_due_to', '')

    todos_all = Todo.query.filter_by(project_id=project.id)\
        .order_by(Todo.is_done, Todo.created_at.desc()).all()
    todos = list(todos_all)

    if todo_filter_assignee:
        if todo_filter_assignee == 'unassigned':
            todos = [t for t in todos if not t.assigned_to]
        else:
            try:
                target_id = int(todo_filter_assignee)
                todos = [t for t in todos if t.assigned_to == target_id]
            except ValueError:
                pass

    if todo_filter_status:
        if todo_filter_status == 'done':
            todos = [t for t in todos if t.is_done]
        elif todo_filter_status == 'overdue':
            todos = [t for t in todos if t.is_overdue]
        elif todo_filter_status == 'new':
            todos = [t for t in todos if not t.is_done and not t.is_overdue]

    if todo_filter_due_from:
        try:
            d = datetime.strptime(todo_filter_due_from, '%Y-%m-%d')
            todos = [t for t in todos if t.due_date and t.due_date >= d]
        except ValueError:
            pass

    if todo_filter_due_to:
        try:
            d = datetime.strptime(todo_filter_due_to, '%Y-%m-%d')
            todos = [t for t in todos if t.due_date and t.due_date <= d]
        except ValueError:
            pass

    # ------------------------------------------------
    #  ОСТАЛЬНЫЕ ДАННЫЕ
    # ------------------------------------------------
    messages = Message.query.filter_by(project_id=project.id)\
        .order_by(Message.created_at.asc()).all()
    folders = Folder.query.filter_by(project_id=project.id, parent_folder_id=None).all()
    files = File.query.filter_by(project_id=project.id, folder_id=None, task_id=None).all()

    milestones = Milestone.query.filter_by(project_id=project.id)\
        .order_by(Milestone.order_index).all()
    reports = Report.query.filter_by(project_id=project.id)\
        .order_by(Report.created_at.desc()).all()
    events = Event.query.filter_by(project_id=project.id, event_type='project')\
        .order_by(Event.start_time).all()

    overdue_milestones = [m for m in milestones if m.is_overdue]
    overdue_tasks = [t for t in tasks_all if t.is_overdue]

    # ------------------------------------------------
    #  КОНТАКТНЫЕ ЛИЦА
    # ------------------------------------------------
    contact_persons = []
    if project.customer:
        contact_persons.extend(project.customer.contacts)
    if project.supplier:
        contact_persons.extend(project.supplier.contacts)
    if project.subcontractor:
        contact_persons.extend(project.subcontractor.contacts)

    return render_template('project.html',
                           project=project,
                           members=members,
                           contact_persons=contact_persons,
                           tasks=tasks,
                           tasks_all=tasks_all,
                           messages=messages,
                           folders=folders,
                           files=files,
                           all_users=User.query.filter(User.role != 'admin').all(),
                           user=user,
                           user_role=get_user_role_in_project(project_id),
                           milestones=milestones,
                           todos=todos,
                           reports=reports,
                           events=events,
                           now=utcnow(),
                           projects=get_user_projects(user),
                           can_manage=can_manage_project(project_id),
                           overdue_milestones=overdue_milestones,
                           overdue_tasks=overdue_tasks,
                           project_overdue=project.is_overdue,
                           project_days_overdue=project.days_overdue,
                           todo_stats=get_todo_stats(project.id),
                           # Фильтры
                           filter_assignee=filter_assignee,
                           filter_status=filter_status,
                           filter_due_from=filter_due_from,
                           filter_due_to=filter_due_to,
                           todo_filter_assignee=todo_filter_assignee,
                           todo_filter_status=todo_filter_status,
                           todo_filter_due_from=todo_filter_due_from,
                           todo_filter_due_to=todo_filter_due_to)


# ============================================================
#  РЕДАКТИРОВАНИЕ ПРОЕКТА
# ============================================================

@bp.route('/project/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    if not can_manage_project(project_id):
        flash('Только руководитель может редактировать проект.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    project = Project.query.get_or_404(project_id)
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        project.name = request.form['name']
        project.description = request.form.get('description', '')
        project.status = request.form.get('status', 'active')

        customer_id = request.form.get('customer_id') or None
        project.customer_id = int(customer_id) if customer_id else None

        supplier_id = request.form.get('supplier_id') or None
        project.supplier_id = int(supplier_id) if supplier_id else None

        subcontractor_id = request.form.get('subcontractor_id') or None
        project.subcontractor_id = int(subcontractor_id) if subcontractor_id else None

        project.start_date = (
            datetime.strptime(request.form['start_date'], '%Y-%m-%d')
            if request.form.get('start_date') else None
        )
        project.end_date = (
            datetime.strptime(request.form['end_date'], '%Y-%m-%d')
            if request.form.get('end_date') else None
        )

        db.session.commit()
        flash('Проект обновлён!', 'success')
        return redirect(url_for('projects.view_project', project_id=project.id))

    # --- GET ---
    suppliers, subcontractors = _split_suppliers_by_type(user)

    return render_template('edit_project.html',
                           project=project,
                           customers=get_available_customers(user),
                           suppliers=suppliers,
                           subcontractors=subcontractors,
                           user=user,
                           user_role=get_user_role_in_project(project_id),
                           projects=get_user_projects(user))


# ============================================================
#  УДАЛЕНИЕ ПРОЕКТА
# ============================================================

@bp.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    import os
    from flask import current_app

    user = User.query.get(session['user_id'])
    project = Project.query.get_or_404(project_id)

    is_allowed = user.role == 'admin'
    if not is_allowed:
        member = ProjectMember.query.filter_by(
            user_id=user.id, project_id=project_id
        ).first()
        if member and not member.is_guest and member.role_in_project == 'admin':
            is_allowed = True

    if not is_allowed:
        flash('Только руководитель проекта может его удалить.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    if request.form.get('confirm_text', '').strip().upper() != 'УДАЛИТЬ':
        flash('Введите слово УДАЛИТЬ для подтверждения.', 'warning')
        return redirect(url_for('projects.view_project', project_id=project_id))

    project_name = project.name

    for file in File.query.filter_by(project_id=project_id).all():
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], file.stored_name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    for task in Task.query.filter_by(project_id=project_id).all():
        for sub in Task.query.filter_by(parent_task_id=task.id).all():
            db.session.delete(sub)

    db.session.delete(project)
    db.session.commit()

    flash(f'Проект «{project_name}» удалён.', 'success')
    return redirect(url_for('dashboard.dashboard'))


# ============================================================
#  СОЗДАНИЕ ЗАДАЧИ
# ============================================================

@bp.route('/project/<int:project_id>/task/create', methods=['POST'])
@login_required
def create_task(project_id):
    if not check_full_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    due_date = None
    if request.form.get('due_date'):
        due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d')

    assigned = request.form.get('assigned_to')  # "user:5" или "contact:3"
    parent_task_id = request.form.get('parent_task_id')
    milestone_id = request.form.get('milestone_id')

    # --- Обработка исполнителя ---
    assigned_to_id = None
    if assigned:
        if ':' in assigned:
            kind, raw_id = assigned.split(':', 1)
        else:
            kind, raw_id = 'user', assigned

        try:
            value_id = int(raw_id)
        except ValueError:
            flash('Некорректный исполнитель.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))

        if kind == 'user':
            member = _validate_project_member(project_id, value_id)
            if not member:
                flash('Выбранный исполнитель не является участником проекта.', 'danger')
                return redirect(url_for('projects.view_project', project_id=project_id))
            if member.is_guest:
                flash('Гость не может быть назначен напрямую. Выберите контактное лицо.', 'danger')
                return redirect(url_for('projects.view_project', project_id=project_id))
            assigned_to_id = member.user_id

        elif kind == 'contact':
            contact = ContactPerson.query.get(value_id)
            if not contact:
                flash('Контактное лицо не найдено.', 'danger')
                return redirect(url_for('projects.view_project', project_id=project_id))

            project = Project.query.get(project_id)
            belongs = False
            if contact.customer_id and project.customer_id == contact.customer_id:
                belongs = True
            if contact.supplier_id and project.supplier_id == contact.supplier_id:
                belongs = True
            if contact.supplier_id and project.subcontractor_id == contact.supplier_id:
                belongs = True

            if not belongs:
                flash('Это контактное лицо не связано с проектом.', 'danger')
                return redirect(url_for('projects.view_project', project_id=project_id))

            guest_user = get_or_create_guest_user(contact)
            add_guest_to_project(guest_user.id, project_id, session['user_id'])
            assigned_to_id = guest_user.id

        else:
            flash('Некорректный тип исполнителя.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))

    # --- Родительская задача ---
    parent_id_int = None
    if parent_task_id:
        parent = _validate_task_in_project(int(parent_task_id), project_id)
        if not parent:
            flash('Родительская задача не найдена в этом проекте.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))
        parent_id_int = parent.id

    # --- Веха ---
    milestone_id_int = None
    if milestone_id:
        ms = _validate_milestone_in_project(int(milestone_id), project_id)
        if not ms:
            flash('Веха не найдена в этом проекте.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))
        milestone_id_int = ms.id

    task = Task(
        title=request.form['title'],
        description=request.form.get('description', ''),
        project_id=project_id,
        assigned_to=assigned_to_id,
        due_date=due_date,
        created_by=session['user_id'],
        parent_task_id=parent_id_int,
        milestone_id=milestone_id_int,
    )
    db.session.add(task)
    db.session.commit()
    flash('Задача создана!', 'success')

    if parent_id_int:
        return redirect(url_for('tasks.view_task', task_id=parent_id_int))
    return redirect(url_for('projects.view_project', project_id=project_id)
                    + f'?_tab=tasks&created={task.id}')


# ============================================================
#  ВЕХИ
# ============================================================

@bp.route('/project/<int:project_id>/milestone/create', methods=['POST'])
@login_required
def create_milestone(project_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    name = request.form['name']
    desc = request.form.get('description', '')
    due = request.form.get('due_date')
    due_date = datetime.strptime(due, '%Y-%m-%d') if due else None

    last = Milestone.query.filter_by(project_id=project_id)\
        .order_by(Milestone.order_index.desc()).first()
    next_index = (last.order_index + 1) if last else 0

    db.session.add(Milestone(
        name=name, description=desc, project_id=project_id,
        order_index=next_index, due_date=due_date,
        created_by=session['user_id']
    ))
    db.session.commit()
    flash('Веха добавлена!', 'success')
    return redirect(url_for('projects.view_project', project_id=project_id))


@bp.route('/milestone/<int:milestone_id>/toggle', methods=['POST'])
@login_required
def toggle_milestone(milestone_id):
    m = Milestone.query.get_or_404(milestone_id)
    if not can_manage_project(m.project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=m.project_id))

    m.is_completed = not m.is_completed
    m.completed_at = utcnow() if m.is_completed else None
    db.session.commit()
    flash('Веха обновлена.', 'success')
    return redirect(url_for('projects.view_project', project_id=m.project_id))


@bp.route('/milestone/<int:milestone_id>/delete', methods=['POST'])
@login_required
def delete_milestone(milestone_id):
    m = Milestone.query.get_or_404(milestone_id)
    pid = m.project_id
    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid))

    db.session.delete(m)
    db.session.commit()
    flash('Веха удалена.', 'info')
    return redirect(url_for('projects.view_project', project_id=pid))