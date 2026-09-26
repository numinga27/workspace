from datetime import datetime, timezone
from flask import session


# ============================================================
#  ВРЕМЯ
# ============================================================

def utcnow():
    """Возвращает текущее UTC-время как naive datetime.
    Заменяет deprecated datetime.utcnow() в Python 3.12+."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
#  ДОСТУП К ПРОЕКТУ
# ============================================================

def check_project_access(project_id, allow_guest=True):
    """Проверяет доступ к проекту.
    Гости по умолчанию имеют доступ к проекту (но ограниченный — только свои задачи).
    Если allow_guest=False — гости НЕ получают доступ (для страницы проекта)."""
    from models import User, ProjectMember
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        return True

    member = ProjectMember.query.filter_by(user_id=user.id, project_id=project_id).first()
    if not member:
        return False

    if member.is_guest and not allow_guest:
        return False

    return True


def check_full_project_access(project_id):
    """Полный доступ к проекту (без гостей)."""
    return check_project_access(project_id, allow_guest=False)


def get_user_role_in_project(project_id):
    """Возвращает роль пользователя в проекте. Для глобадмина — 'admin'."""
    from models import User, ProjectMember
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        return 'admin'
    member = ProjectMember.query.filter_by(user_id=user.id, project_id=project_id).first()
    return member.role_in_project if member else None


def can_manage_project(project_id):
    """Может ли пользователь управлять проектом (не гость, роль admin/manager)."""
    from models import User, ProjectMember
    user = User.query.get(session['user_id'])
    if user.role == 'admin':
        return True
    member = ProjectMember.query.filter_by(user_id=user.id, project_id=project_id).first()
    if not member or member.is_guest:
        return False
    return member.role_in_project in ['admin', 'manager']


def is_project_guest(user_id, project_id):
    """Проверяет, является ли пользователь гостем проекта."""
    from models import ProjectMember
    if not user_id:
        return False
    member = ProjectMember.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()
    return member is not None and member.is_guest


# ============================================================
#  СПИСКИ ПРОЕКТОВ
# ============================================================

def get_user_projects(user):
    """Возвращает список проектов пользователя (без гостевых)."""
    from models import Project
    if user.role == 'admin':
        return Project.query.filter_by(is_active=True).all()
    # Исключаем проекты, где пользователь — гость
    return [m.project for m in user.projects if not m.is_guest]


# ============================================================
#  ЗАКАЗЧИКИ
# ============================================================

def get_available_customers(user):
    """Возвращает список доступных заказчиков для пользователя."""
    from models import Customer, Project
    from extensions import db

    if user.role == 'admin':
        return Customer.query.order_by(Customer.name).all()

    # ID заказчиков, привязанных к проектам пользователя
    my_customer_ids = set()
    for member in user.projects:
        if member.project.customer_id:
            my_customer_ids.add(member.project.customer_id)

    # Заказчики, ещё не привязанные ни к одному проекту — видны всем
    bound_ids = set()
    for (cid,) in db.session.query(Project.customer_id).filter(Project.customer_id.isnot(None)).all():
        bound_ids.add(cid)

    unassigned = Customer.query.filter(~Customer.id.in_(bound_ids)).all() if bound_ids else Customer.query.all()
    assigned = Customer.query.filter(Customer.id.in_(my_customer_ids)).all() if my_customer_ids else []

    return sorted(set(assigned) | set(unassigned), key=lambda c: c.name.lower())


# ============================================================
#  ПОСТАВЩИКИ / СУБПОДРЯДЧИКИ
# ============================================================

def get_available_suppliers(user):
    """Возвращает список доступных поставщиков И субподрядчиков
    (без фильтра по типу — фильтр делается в blueprint)."""
    from models import Supplier, Project
    from extensions import db

    if user.role == 'admin':
        return Supplier.query.order_by(Supplier.name).all()

    # ID поставщиков/субподрядчиков, привязанных к проектам пользователя
    my_supplier_ids = set()
    for member in user.projects:
        if member.project.supplier_id:
            my_supplier_ids.add(member.project.supplier_id)
        if member.project.subcontractor_id:  # ← НОВОЕ: учитываем субподрядчиков
            my_supplier_ids.add(member.project.subcontractor_id)

    # ID, привязанные к проектам (ни как поставщик, ни как субподрядчик)
    bound_ids = set()
    for (sid,) in db.session.query(Project.supplier_id).filter(Project.supplier_id.isnot(None)).all():
        bound_ids.add(sid)
    for (sid,) in db.session.query(Project.subcontractor_id).filter(Project.subcontractor_id.isnot(None)).all():
        bound_ids.add(sid)

    unassigned = Supplier.query.filter(~Supplier.id.in_(bound_ids)).all() if bound_ids else Supplier.query.all()
    assigned = Supplier.query.filter(Supplier.id.in_(my_supplier_ids)).all() if my_supplier_ids else []

    return sorted(set(assigned) | set(unassigned), key=lambda s: s.name.lower())


# ============================================================
#  ВАЛИДАЦИЯ ПРИНАДЛЕЖНОСТИ ПРОЕКТУ
# ============================================================

def _validate_project_member(project_id, user_id):
    """Проверяет, что user_id — участник проекта project_id."""
    from models import ProjectMember
    if not user_id:
        return None
    return ProjectMember.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()


def _validate_task_in_project(task_id, project_id):
    """Проверяет, что задача принадлежит проекту project_id."""
    from models import Task
    if not task_id:
        return None
    return Task.query.filter_by(id=task_id, project_id=project_id).first()


def _validate_milestone_in_project(milestone_id, project_id):
    """Проверяет, что веха принадлежит проекту project_id."""
    from models import Milestone
    if not milestone_id:
        return None
    return Milestone.query.filter_by(id=milestone_id, project_id=project_id).first()


def _validate_folder_in_project(folder_id, project_id):
    """Проверяет, что папка принадлежит проекту project_id."""
    from models import Folder
    if not folder_id:
        return None
    return Folder.query.filter_by(id=folder_id, project_id=project_id).first()


# ============================================================
#  ГОСТЕВОЙ ДОСТУП
# ============================================================

def get_contact_for_user(user_id):
    """Возвращает ContactPerson, привязанный к юзеру (если есть)."""
    from models import ContactPerson
    return ContactPerson.query.filter_by(user_id=user_id).first()


def get_or_create_guest_user(contact_person):
    """Создаёт или возвращает User для контактного лица.
    Если у контакта уже есть user_id — возвращает его.
    Если нет — создаёт User с ролью 'user' и случайным паролем."""
    from models import User
    from extensions import db
    import secrets as _secrets

    if contact_person.user_id:
        return User.query.get(contact_person.user_id)

    # Если email уже занят — используем существующего юзера
    if contact_person.email:
        existing = User.query.filter_by(email=contact_person.email).first()
        if existing:
            contact_person.user_id = existing.id
            db.session.commit()
            return existing

    # Создаём нового
    email = contact_person.email or f'contact_{contact_person.id}@guest.local'

    # Разбор ФИО
    parts = (contact_person.full_name or 'Гость').split()
    first_name = parts[0][:50] if parts else 'Гость'
    last_name = ' '.join(parts[1:])[:50] if len(parts) > 1 else '—'

    user = User(
        first_name=first_name,
        last_name=last_name,
        company=(contact_person.belongs_to.name if contact_person.belongs_to else 'Внешний')[:100],
        email=email,
        role='user',
        is_active=True,
    )
    user.set_password(_secrets.token_urlsafe(16))
    db.session.add(user)
    db.session.flush()  # получить user.id

    contact_person.user_id = user.id
    db.session.commit()
    return user


def add_guest_to_project(user_id, project_id, invited_by):
    """Добавляет пользователя как гостя в проект (если ещё не добавлен)."""
    from models import ProjectMember
    from extensions import db

    existing = ProjectMember.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()

    if existing:
        if not existing.is_guest:
            existing.is_guest = True
            db.session.commit()
        return existing

    member = ProjectMember(
        user_id=user_id,
        project_id=project_id,
        role_in_project='member',
        is_guest=True,
    )
    db.session.add(member)
    db.session.commit()
    return member


# ============================================================
#  НЕПРОЧИТАННЫЕ СООБЩЕНИЯ
# ============================================================

def get_unread_counts(user):
    """Возвращает словарь {project_id: count_unread} для пользователя."""
    from models import MessageRead, Message, Project

    if user.role == 'admin':
        projects = Project.query.filter_by(is_active=True).all()
    else:
        projects = [m.project for m in user.projects if not m.is_guest]

    unread = {}
    for project in projects:
        read_record = MessageRead.query.filter_by(
            user_id=user.id, project_id=project.id
        ).first()

        if read_record:
            count = Message.query.filter(
                Message.project_id == project.id,
                Message.user_id != user.id,
                Message.created_at > read_record.last_read_at
            ).count()
        else:
            count = Message.query.filter(
                Message.project_id == project.id,
                Message.user_id != user.id
            ).count()

        if count > 0:
            unread[project.id] = count

    return unread


def mark_project_as_read(user_id, project_id):
    """Отмечает чат проекта как прочитанный."""
    from models import MessageRead
    from extensions import db

    record = MessageRead.query.filter_by(user_id=user_id, project_id=project_id).first()

    if record:
        record.last_read_at = utcnow()
    else:
        record = MessageRead(
            user_id=user_id,
            project_id=project_id,
            last_read_at=utcnow()
        )
        db.session.add(record)

    db.session.commit()


# ============================================================
#  НЕПРОЧИТАННЫЕ ЗАДАЧИ / TO-DO
# ============================================================

def get_unread_task_ids(user_id):
    """Возвращает set() ID задач, которые назначены пользователю и не прочитаны."""
    from models import Task, TaskRead
    assigned_task_ids = {
        t.id for t in Task.query.filter_by(assigned_to=user_id).all()
    }
    read_task_ids = {
        r.task_id for r in TaskRead.query.filter_by(user_id=user_id).all()
    }
    return assigned_task_ids - read_task_ids


def get_unread_todo_ids(user_id):
    """Возвращает set() ID To-Do, назначенных пользователю и не прочитанных."""
    from models import Todo, TodoRead
    assigned_ids = {
        t.id for t in Todo.query.filter_by(assigned_to=user_id).all()
    }
    read_ids = {
        r.todo_id for r in TodoRead.query.filter_by(user_id=user_id).all()
    }
    return assigned_ids - read_ids


def get_unread_tasks_count(user_id):
    """Сколько непрочитанных задач назначено пользователю."""
    return len(get_unread_task_ids(user_id))


def mark_task_as_read(user_id, task_id):
    """Отмечает задачу как прочитанную пользователем."""
    from models import TaskRead
    from extensions import db

    existing = TaskRead.query.filter_by(user_id=user_id, task_id=task_id).first()
    if not existing:
        db.session.add(TaskRead(user_id=user_id, task_id=task_id))
        db.session.commit()


def mark_todo_as_read(user_id, todo_id):
    """Отмечает To-Do как прочитанное."""
    from models import TodoRead
    from extensions import db

    existing = TodoRead.query.filter_by(user_id=user_id, todo_id=todo_id).first()
    if not existing:
        db.session.add(TodoRead(user_id=user_id, todo_id=todo_id))
        db.session.commit()    