from datetime import datetime, timezone
from extensions import db


def _utcnow():
    """Возвращает текущее UTC-время как naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
#  ПОЛЬЗОВАТЕЛЬ
# ============================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    # ---- Методы работы с паролем ----
    def set_password(self, raw_password):
        from werkzeug.security import generate_password_hash
        self.password = generate_password_hash(raw_password, method='pbkdf2:sha256')

    def check_password(self, raw_password):
        from werkzeug.security import check_password_hash
        if self.password.startswith(('pbkdf2:', 'scrypt:', 'argon2')):
            return check_password_hash(self.password, raw_password)
        # Обратная совместимость со старыми plain-text паролями
        return self.password == raw_password

    # ---- Relationships ----
    projects = db.relationship('ProjectMember', back_populates='user', lazy=True)
    created_projects = db.relationship(
        'Project', backref='creator', lazy=True, foreign_keys='Project.created_by'
    )
    assigned_tasks = db.relationship(
        'Task', backref='assignee', lazy=True, foreign_keys='Task.assigned_to'
    )
    created_tasks = db.relationship(
        'Task', backref='task_creator', lazy=True, foreign_keys='Task.created_by'
    )
    messages = db.relationship('Message', backref='author', lazy=True)
    uploaded_files = db.relationship('File', backref='uploader', lazy=True)
    invitations_sent = db.relationship(
        'Invitation', backref='inviter', lazy=True, foreign_keys='Invitation.invited_by'
    )
    created_milestones = db.relationship(
        'Milestone', backref='milestone_creator', lazy=True, foreign_keys='Milestone.created_by'
    )
    todos_assigned = db.relationship(
        'Todo', backref='todo_assignee', lazy=True, foreign_keys='Todo.assigned_to'
    )
    todos_created = db.relationship(
        'Todo', backref='todo_creator', lazy=True, foreign_keys='Todo.created_by'
    )
    reports = db.relationship('Report', backref='report_author', lazy=True)

    # Обратная связь с контактным лицом (если этот юзер — гость из контакта)
    contact_profile = db.relationship(
        'ContactPerson', backref='user', uselist=False,
        foreign_keys='ContactPerson.user_id'
    )


# ============================================================
#  ЗАКАЗЧИК
# ============================================================

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    inn = db.Column(db.String(20), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)   # legacy-поле
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    projects = db.relationship('Project', backref='customer', lazy=True)
    contacts = db.relationship(
        'ContactPerson', backref='customer', lazy=True,
        cascade='all, delete-orphan',
        foreign_keys='ContactPerson.customer_id'
    )


# ============================================================
#  ПОСТАВЩИК / СУБПОДРЯДЧИК
# ============================================================

class Supplier(db.Model):
    """Поставщик или субподрядчик.
    Различается по полю supplier_type:
      - 'supplier' — обычный поставщик
      - 'subcontractor' — субподрядчик
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    inn = db.Column(db.String(20), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)   # legacy-поле
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(300), nullable=True)

    # ← НОВОЕ: тип
    supplier_type = db.Column(db.String(20), default='supplier')  # 'supplier' | 'subcontractor'

    created_at = db.Column(db.DateTime, default=_utcnow)

    # Основной backref — для supplier_id у проекта
    projects = db.relationship(
        'Project', backref='supplier', lazy=True,
        foreign_keys='Project.supplier_id'
    )
    # ← НОВОЕ: обратная связь для subcontractor_id у проекта
    subcontractor_projects = db.relationship(
        'Project', backref='subcontractor', lazy=True,
        foreign_keys='Project.subcontractor_id'
    )

    contacts = db.relationship(
        'ContactPerson', backref='supplier', lazy=True,
        cascade='all, delete-orphan',
        foreign_keys='ContactPerson.supplier_id'
    )

    @property
    def is_subcontractor(self):
        return self.supplier_type == 'subcontractor'

    @property
    def type_display(self):
        return 'Субподрядчик' if self.is_subcontractor else 'Поставщик'


# ============================================================
#  КОНТАКТНОЕ ЛИЦО
# ============================================================

class ContactPerson(db.Model):
    """Контактное лицо заказчика или поставщика/субподрядчика.
    Может быть связано с User — если этот контакт является «гостем» в системе."""
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    position = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(100), nullable=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)

    # Ссылка на User, если контакт зарегистрирован в системе
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.CheckConstraint(
            '(customer_id IS NOT NULL AND supplier_id IS NULL) OR '
            '(customer_id IS NULL AND supplier_id IS NOT NULL)',
            name='contact_belongs_to_one'
        ),
    )

    @property
    def belongs_to(self):
        """Возвращает компанию (Customer или Supplier)."""
        if self.customer:
            return self.customer
        return self.supplier

    @property
    def belongs_to_type(self):
        return 'customer' if self.customer_id else 'supplier'


# ============================================================
#  ПРОЕКТ
# ============================================================

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    is_active = db.Column(db.Boolean, default=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)

    # ← НОВОЕ: субподрядчик
    subcontractor_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)

    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='active')

    @property
    def completion_percentage(self):
        tasks = Task.query.filter_by(project_id=self.id, parent_task_id=None).all()
        if not tasks:
            milestones = Milestone.query.filter_by(project_id=self.id).all()
            if not milestones:
                return 0
            done = sum(1 for m in milestones if m.is_completed)
            return int((done / len(milestones)) * 100)
        completed = sum(1 for t in tasks if t.status == 'completed')
        return int((completed / len(tasks)) * 100)

    @property
    def current_milestone(self):
        milestones = Milestone.query.filter_by(project_id=self.id)\
            .order_by(Milestone.order_index).all()
        for m in milestones:
            if not m.is_completed:
                return m
        return milestones[-1] if milestones else None

    @property
    def is_overdue(self):
        if self.status == 'completed' or not self.end_date:
            return False
        return self.end_date < _utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (_utcnow() - self.end_date).days

    members = db.relationship(
        'ProjectMember', back_populates='project', lazy=True,
        cascade='all, delete-orphan'
    )
    tasks = db.relationship(
        'Task', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    messages = db.relationship(
        'Message', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    folders = db.relationship(
        'Folder', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    files = db.relationship(
        'File', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    invitations = db.relationship(
        'Invitation', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    milestones = db.relationship(
        'Milestone', backref='project', lazy=True,
        order_by='Milestone.order_index',
        cascade='all, delete-orphan'
    )
    reports = db.relationship(
        'Report', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    todos = db.relationship(
        'Todo', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    events = db.relationship(
        'Event', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )
    message_reads = db.relationship(
        'MessageRead', backref='project', lazy=True,
        cascade='all, delete-orphan'
    )


# ============================================================
#  ВЕХА
# ============================================================

class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    order_index = db.Column(db.Integer, default=0)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    @property
    def is_overdue(self):
        if self.is_completed or not self.due_date:
            return False
        return self.due_date < _utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (_utcnow() - self.due_date).days

    @property
    def days_left(self):
        if self.is_completed or not self.due_date:
            return None
        delta = self.due_date - _utcnow()
        return delta.days if delta.days >= 0 else 0


# ============================================================
#  УЧАСТНИК ПРОЕКТА (с флагом гостя)
# ============================================================

class ProjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    role_in_project = db.Column(db.String(30), default='member')
    joined_at = db.Column(db.DateTime, default=_utcnow)

    # Гость — видит только свои задачи, не видит проект целиком
    is_guest = db.Column(db.Boolean, default=False)

    user = db.relationship('User', back_populates='projects')
    project = db.relationship('Project', back_populates='members')

    ROLE_NAMES = {
        'admin': 'Руководитель проекта',
        'manager': 'Менеджер',
        'chief_engineer': 'Главный инженер',
        'logistic': 'Логистик',
        'member': 'Участник',
    }

    @property
    def role_display(self):
        if self.is_guest:
            return 'Гость'
        return self.ROLE_NAMES.get(self.role_in_project, self.role_in_project)


# ============================================================
#  ЗАДАЧА
# ============================================================

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='new')
    start_date = db.Column(db.DateTime, default=_utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    parent_task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    parent_task = db.relationship('Task', remote_side=[id], backref='subtasks')

    milestone_id = db.Column(db.Integer, db.ForeignKey('milestone.id'), nullable=True)
    comment = db.Column(db.Text, nullable=True)

    files = db.relationship('File', backref='task', lazy=True)
    milestone = db.relationship('Milestone', backref='tasks')

    @property
    def is_overdue(self):
        if self.status == 'completed' or not self.due_date:
            return False
        return self.due_date < _utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (_utcnow() - self.due_date).days


# ============================================================
#  TO-DO
# ============================================================

class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    is_done = db.Column(db.Boolean, default=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    done_at = db.Column(db.DateTime, nullable=True)

    due_date = db.Column(db.DateTime, nullable=True)
    comment = db.Column(db.Text, nullable=True)

    @property
    def is_overdue(self):
        if self.is_done or not self.due_date:
            return False
        return self.due_date < _utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (_utcnow() - self.due_date).days

    @property
    def status_key(self):
        if self.is_done:
            return 'done'
        if self.is_overdue:
            return 'overdue'
        return 'new'


# ============================================================
#  СОБЫТИЕ
# ============================================================

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    all_day = db.Column(db.Boolean, default=False)
    color = db.Column(db.String(20), default='blue')

    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    event_type = db.Column(db.String(20), default='project')
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by], backref='events_created')
    owner = db.relationship('User', foreign_keys=[owner_id], backref='personal_events')

    COLOR_MAP = {
        'blue':   '#5b5bd6',
        'green':  '#16a34a',
        'red':    '#dc2626',
        'orange': '#f59e0b',
        'purple': '#8b5cf6',
        'teal':   '#0891b2',
    }

    @property
    def color_hex(self):
        return self.COLOR_MAP.get(self.color, '#5b5bd6')

    @property
    def is_personal(self):
        return self.event_type == 'personal'


# ============================================================
#  ОТЧЁТ
# ============================================================

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestone.id'), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    reason = db.Column(db.String(50), default='on_track')
    reason_detail = db.Column(db.Text, nullable=True)
    delay_days = db.Column(db.Integer, default=0)

    milestone = db.relationship('Milestone')

    REASON_NAMES = {
        'on_track': ('Всё по плану', 'success'),
        'delay_supply': ('Задержка поставки', 'warning'),
        'scope_change': ('Изменение ТЗ', 'info'),
        'contractor': ('Проблема с подрядчиком', 'warning'),
        'force_majeure': ('Форс-мажор', 'danger'),
        'budget': ('Проблемы с бюджетом', 'danger'),
        'other': ('Другое', 'secondary'),
    }

    @property
    def reason_display(self):
        return self.REASON_NAMES.get(self.reason, ('—', 'secondary'))

    @property
    def reason_color(self):
        return self.REASON_NAMES.get(self.reason, ('—', 'secondary'))[1]


# ============================================================
#  СООБЩЕНИЕ И ПРОЧИТАННОЕ
# ============================================================

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)


class MessageRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    last_read_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'project_id', name='unique_user_project_read'),
    )

    user = db.relationship('User', backref='message_reads')


# ============================================================
#  ПАПКИ И ФАЙЛЫ
# ============================================================

class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    parent = db.relationship('Folder', remote_side=[id], backref='subfolders')
    files = db.relationship('File', backref='folder', lazy=True)


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    file_type = db.Column(db.String(100), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=_utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


# ============================================================
#  ПРИГЛАШЕНИЕ
# ============================================================

class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    invited_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(30), default='member')
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)


class TaskRead(db.Model):
    """Отслеживает, какие задачи пользователь уже посмотрел.
    Если записи нет — задача считается новой (непрочитанной)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'task_id', name='unique_user_task_read'),
    )

    user = db.relationship('User', backref='task_reads')
    task = db.relationship('Task', backref='read_marks')


class TodoRead(db.Model):
    """Отслеживает прочитанные To-Do."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    todo_id = db.Column(db.Integer, db.ForeignKey('todo.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'todo_id', name='unique_user_todo_read'),
    )

    user = db.relationship('User', backref='todo_reads')
    todo = db.relationship('Todo', backref='read_marks')    