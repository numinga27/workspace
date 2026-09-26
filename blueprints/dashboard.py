from datetime import datetime
from flask import Blueprint, render_template, request, session, jsonify, url_for
from sqlalchemy import or_

from models import (
    User, Project, Task, Todo,
    Customer, Supplier, ContactPerson,
)
from decorators import login_required
from utils import (
    get_user_projects, get_available_customers, is_project_guest,
    # ← НОВОЕ: для уведомлений
    get_unread_task_ids, get_unread_todo_ids,
)

bp = Blueprint('dashboard', __name__)


# ============================================================
#  ДАШБОРД
# ============================================================

@bp.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    projects = get_user_projects(user)

    filter_customer = request.args.get('customer', '')
    filter_start_from = request.args.get('start_from', '')
    filter_start_to = request.args.get('start_to', '')
    filter_status = request.args.get('status', '')

    filtered = projects

    if filter_customer:
        filtered = [p for p in filtered if p.customer and str(p.customer.id) == filter_customer]

    if filter_start_from:
        try:
            d = datetime.strptime(filter_start_from, '%Y-%m-%d')
            filtered = [p for p in filtered if p.start_date and p.start_date >= d]
        except ValueError:
            pass

    if filter_start_to:
        try:
            d = datetime.strptime(filter_start_to, '%Y-%m-%d')
            filtered = [p for p in filtered if p.start_date and p.start_date <= d]
        except ValueError:
            pass

    if filter_status:
        filtered = [p for p in filtered if p.status == filter_status]

    customers = get_available_customers(user)

    # ← НОВОЕ: непрочитанные задачи и To-Do для бейджей
    unread_task_ids = get_unread_task_ids(user.id)
    unread_todo_ids = get_unread_todo_ids(user.id)

    # ← НОВОЕ: задачи пользователя для карточек на дашборде
    my_active_tasks = Task.query.filter_by(assigned_to=user.id)\
        .filter(Task.status.in_(['new', 'in_progress']))\
        .order_by(Task.due_date.asc().nullslast()).all()

    # Срочные (дедлайн ≤ 3 дней)
    from utils import utcnow
    now = utcnow()
    urgent_tasks = []
    for t in my_active_tasks:
        if t.due_date:
            days_left = (t.due_date - now).days
            if 0 <= days_left <= 3:
                urgent_tasks.append(t)

    return render_template('dashboard.html',
                           projects=filtered,
                           all_projects=projects,
                           customers=customers,
                           user=user,
                           filter_customer=filter_customer,
                           filter_start_from=filter_start_from,
                           filter_start_to=filter_start_to,
                           filter_status=filter_status,
                           unread_task_ids=unread_task_ids,
                           unread_todo_ids=unread_todo_ids,
                           my_active_tasks=my_active_tasks,
                           urgent_tasks=urgent_tasks,
                           now=now)


# ============================================================
#  ГЛОБАЛЬНЫЙ ПОИСК (Ctrl+K)
# ============================================================

@bp.route('/api/search')
@login_required
def api_search():
    """Поиск по проектам, задачам, To-Do, заказчикам, поставщикам и контактам."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    user = User.query.get(session['user_id'])
    is_admin = user.role == 'admin'

    if is_admin:
        projects = Project.query.filter_by(is_active=True).all()
    else:
        projects = [m.project for m in user.projects if not m.is_guest]

    project_ids = [p.id for p in projects]
    customer_ids = {p.customer_id for p in projects if p.customer_id}
    supplier_ids = {p.supplier_id for p in projects if p.supplier_id}

    results = []
    q_lower = q.lower()

    # 1. Проекты
    for p in projects:
        if q_lower in p.name.lower():
            results.append({
                'type': 'project',
                'icon': 'folder-fill',
                'title': p.name,
                'subtitle': f'Проект · {p.completion_percentage}%',
                'url': url_for('projects.view_project', project_id=p.id),
            })

    # 2. Задачи и 3. To-Do
    if project_ids:
        tasks = Task.query.filter(
            Task.project_id.in_(project_ids),
            Task.title.ilike(f'%{q}%')
        ).order_by(Task.created_at.desc()).limit(15).all()

        for t in tasks:
            status_icon = '🆕'
            if t.status == 'completed':
                status_icon = '✅'
            elif t.status == 'in_progress':
                status_icon = '🔄'
            elif t.is_overdue:
                status_icon = '⚠️'

            results.append({
                'type': 'task',
                'icon': 'list-task',
                'title': t.title,
                'subtitle': f'Задача · {t.project.name} · {status_icon}',
                'url': url_for('tasks.view_task', task_id=t.id),
            })

        todos = Todo.query.filter(
            Todo.project_id.in_(project_ids),
            Todo.title.ilike(f'%{q}%')
        ).order_by(Todo.created_at.desc()).limit(10).all()

        for todo in todos:
            if todo.is_done:
                status_icon = '✅'
            elif todo.is_overdue:
                status_icon = '⚠️'
            else:
                status_icon = '⚪'

            results.append({
                'type': 'todo',
                'icon': 'check2-square',
                'title': todo.title,
                'subtitle': f'To-Do · {todo.project.name} · {status_icon}',
                'url': url_for('projects.view_project', project_id=todo.project_id) + '#todo',
            })

    # 4. Заказчики
    if is_admin:
        customers = Customer.query.filter(Customer.name.ilike(f'%{q}%')).order_by(Customer.name).limit(10).all()
    else:
        customers = Customer.query.filter(
            Customer.id.in_(customer_ids),
            Customer.name.ilike(f'%{q}%')
        ).order_by(Customer.name).limit(10).all() if customer_ids else []

    for c in customers:
        contacts_count = len(c.contacts) if c.contacts else 0
        results.append({
            'type': 'customer',
            'icon': 'buildings',
            'title': c.name,
            'subtitle': f'Заказчик · {contacts_count} контакт(ов)',
            'url': url_for('customers.view_customer', customer_id=c.id),
        })

    # 5. Поставщики
    if is_admin:
        suppliers = Supplier.query.filter(Supplier.name.ilike(f'%{q}%')).order_by(Supplier.name).limit(10).all()
    else:
        suppliers = Supplier.query.filter(
            Supplier.id.in_(supplier_ids),
            Supplier.name.ilike(f'%{q}%')
        ).order_by(Supplier.name).limit(10).all() if supplier_ids else []

    for s in suppliers:
        contacts_count = len(s.contacts) if s.contacts else 0
        type_label = 'Субподрядчик' if s.is_subcontractor else 'Поставщик'
        results.append({
            'type': 'supplier',
            'icon': 'truck' if not s.is_subcontractor else 'people-fill',
            'title': s.name,
            'subtitle': f'{type_label} · {contacts_count} контакт(ов)',
            'url': (url_for('suppliers.view_subcontractor', supplier_id=s.id)
                    if s.is_subcontractor
                    else url_for('suppliers.view_supplier', supplier_id=s.id)),
        })

    # 6. Контактные лица
    if is_admin:
        contact_query = ContactPerson.query.filter(ContactPerson.full_name.ilike(f'%{q}%'))
    else:
        if customer_ids or supplier_ids:
            conditions = []
            if customer_ids:
                conditions.append(ContactPerson.customer_id.in_(customer_ids))
            if supplier_ids:
                conditions.append(ContactPerson.supplier_id.in_(supplier_ids))
            contact_query = ContactPerson.query.filter(
                ContactPerson.full_name.ilike(f'%{q}%'),
                or_(*conditions),
            )
        else:
            contact_query = None

    if contact_query is not None:
        contacts = contact_query.limit(10).all()

        for c in contacts:
            owner = c.belongs_to
            owner_name = owner.name if owner else '—'
            owner_label = 'Заказчик' if c.customer_id else ('Субподрядчик' if owner and owner.is_subcontractor else 'Поставщик')

            if c.customer_id:
                contact_url = url_for('customers.view_customer', customer_id=c.customer_id)
            elif c.supplier_id:
                # Проверяем, субподрядчик это или поставщик
                owner_supplier = Supplier.query.get(c.supplier_id)
                if owner_supplier and owner_supplier.is_subcontractor:
                    contact_url = url_for('suppliers.view_subcontractor', supplier_id=c.supplier_id)
                else:
                    contact_url = url_for('suppliers.view_supplier', supplier_id=c.supplier_id)
            else:
                contact_url = '#'

            results.append({
                'type': 'contact',
                'icon': 'person-badge',
                'title': c.full_name,
                'subtitle': f'Контакт · {owner_label}: {owner_name}',
                'url': contact_url,
            })

    return jsonify(results[:25])