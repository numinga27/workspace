from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
import os
import uuid
import secrets

# PDF (WeasyPrint)
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    print("⚠️  WeasyPrint не установлен. PDF-отчёты недоступны.")

# Email (Flask-Mail)
try:
    from flask_mail import Mail, Message as MailMessage
    FLASK_MAIL_AVAILABLE = True
except ImportError:
    FLASK_MAIL_AVAILABLE = False
    print("⚠️  Flask-Mail не установлен. Email-уведомления недоступны.")


app = Flask(__name__)
app.secret_key = 'supersecretkey123'

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'workspace.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============================================================
#  НАСТРОЙКИ ПОЧТЫ
# ============================================================
MAIL_CONFIG = {
    'MAIL_SERVER': os.environ.get('MAIL_SERVER', 'smtp.yandex.ru'),
    'MAIL_PORT': int(os.environ.get('MAIL_PORT', 465)),
    'MAIL_USE_SSL': os.environ.get('MAIL_USE_SSL', 'true').lower() == 'true',
    'MAIL_USE_TLS': os.environ.get('MAIL_USE_TLS', 'false').lower() == 'true',
    'MAIL_USERNAME': os.environ.get('MAIL_USERNAME', ''),
    'MAIL_PASSWORD': os.environ.get('MAIL_PASSWORD', ''),
    'MAIL_DEFAULT_SENDER': os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME', ''),
}
app.config.update(MAIL_CONFIG)

db = SQLAlchemy(app)

if FLASK_MAIL_AVAILABLE:
    mail = Mail(app)
else:
    mail = None


# ============================================================
#  МОДЕЛИ
# ============================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship('ProjectMember', back_populates='user', lazy=True)
    created_projects = db.relationship('Project', backref='creator', lazy=True, foreign_keys='Project.created_by')
    assigned_tasks = db.relationship('Task', backref='assignee', lazy=True, foreign_keys='Task.assigned_to')
    created_tasks = db.relationship('Task', backref='task_creator', lazy=True, foreign_keys='Task.created_by')
    messages = db.relationship('Message', backref='author', lazy=True)
    uploaded_files = db.relationship('File', backref='uploader', lazy=True)
    invitations_sent = db.relationship('Invitation', backref='inviter', lazy=True, foreign_keys='Invitation.invited_by')
    created_milestones = db.relationship('Milestone', backref='milestone_creator', lazy=True, foreign_keys='Milestone.created_by')
    todos_assigned = db.relationship('Todo', backref='todo_assignee', lazy=True, foreign_keys='Todo.assigned_to')
    todos_created = db.relationship('Todo', backref='todo_creator', lazy=True, foreign_keys='Todo.created_by')
    reports = db.relationship('Report', backref='report_author', lazy=True)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    inn = db.Column(db.String(20), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship('Project', backref='customer', lazy=True)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
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
        milestones = Milestone.query.filter_by(project_id=self.id).order_by(Milestone.order_index).all()
        for m in milestones:
            if not m.is_completed:
                return m
        return milestones[-1] if milestones else None

    @property
    def is_overdue(self):
        if self.status == 'completed' or not self.end_date:
            return False
        return self.end_date < datetime.utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (datetime.utcnow() - self.end_date).days

    members = db.relationship('ProjectMember', back_populates='project', lazy=True,
                              cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='project', lazy=True,
                            cascade='all, delete-orphan')
    messages = db.relationship('Message', backref='project', lazy=True,
                               cascade='all, delete-orphan')
    folders = db.relationship('Folder', backref='project', lazy=True,
                              cascade='all, delete-orphan')
    files = db.relationship('File', backref='project', lazy=True,
                            cascade='all, delete-orphan')
    invitations = db.relationship('Invitation', backref='project', lazy=True,
                                  cascade='all, delete-orphan')
    milestones = db.relationship('Milestone', backref='project', lazy=True,
                                 order_by='Milestone.order_index',
                                 cascade='all, delete-orphan')
    reports = db.relationship('Report', backref='project', lazy=True,
                              cascade='all, delete-orphan')
    todos = db.relationship('Todo', backref='project', lazy=True,
                            cascade='all, delete-orphan')
    events = db.relationship('Event', backref='project', lazy=True,
                             cascade='all, delete-orphan')
    message_reads = db.relationship('MessageRead', backref='project', lazy=True,
                                    cascade='all, delete-orphan')


class Milestone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    order_index = db.Column(db.Integer, default=0)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    @property
    def is_overdue(self):
        if self.is_completed or not self.due_date:
            return False
        return self.due_date < datetime.utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (datetime.utcnow() - self.due_date).days

    @property
    def days_left(self):
        if self.is_completed or not self.due_date:
            return None
        delta = self.due_date - datetime.utcnow()
        return delta.days if delta.days >= 0 else 0


class ProjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    role_in_project = db.Column(db.String(30), default='member')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        return self.ROLE_NAMES.get(self.role_in_project, self.role_in_project)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='new')
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    parent_task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    parent_task = db.relationship('Task', remote_side=[id], backref='subtasks')

    milestone_id = db.Column(db.Integer, db.ForeignKey('milestone.id'), nullable=True)

    # Комментарий (причина просрочки, пояснения)
    comment = db.Column(db.Text, nullable=True)

    files = db.relationship('File', backref='task', lazy=True)
    milestone = db.relationship('Milestone', backref='tasks')

    @property
    def is_overdue(self):
        if self.status == 'completed' or not self.due_date:
            return False
        return self.due_date < datetime.utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (datetime.utcnow() - self.due_date).days


class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    is_done = db.Column(db.Boolean, default=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    done_at = db.Column(db.DateTime, nullable=True)

    # Новые поля
    due_date = db.Column(db.DateTime, nullable=True)
    comment = db.Column(db.Text, nullable=True)

    @property
    def is_overdue(self):
        if self.is_done or not self.due_date:
            return False
        return self.due_date < datetime.utcnow()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (datetime.utcnow() - self.due_date).days

    @property
    def status_key(self):
        if self.is_done:
            return 'done'
        if self.is_overdue:
            return 'overdue'
        return 'new'


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestone.id'), nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)


class MessageRead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'project_id', name='unique_user_project_read'),
    )

    user = db.relationship('User', backref='message_reads')


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    invited_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(30), default='member')
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)


# ============================================================
#  СОЗДАНИЕ ТАБЛИЦ
# ============================================================
with app.app_context():
    db.create_all()
    if not User.query.first():
        admin = User(
            first_name='Иван',
            last_name='Петров',
            company='ООО Рога и Копыта',
            email='admin@example.com',
            password='admin123',
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()


# ============================================================
#  ДЕКОРАТОРЫ И ХЕЛПЕРЫ
# ============================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        user = db.session.get(User, session['user_id'])
        if user.role != 'admin':
            flash('Доступ запрещен. Только для руководителя.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def check_project_access(project_id):
    user = db.session.get(User, session['user_id'])
    if user.role == 'admin':
        return True
    member = ProjectMember.query.filter_by(user_id=user.id, project_id=project_id).first()
    return member is not None


def get_user_role_in_project(project_id):
    user = db.session.get(User, session['user_id'])
    if user.role == 'admin':
        return 'admin'
    member = ProjectMember.query.filter_by(user_id=user.id, project_id=project_id).first()
    return member.role_in_project if member else None


def can_manage_project(project_id):
    role = get_user_role_in_project(project_id)
    return role in ['admin', 'manager']


def get_user_projects(user):
    if user.role == 'admin':
        return Project.query.filter_by(is_active=True).all()
    result = []
    for member in user.projects:
        result.append(member.project)
    return result


def get_available_customers(user):
    if user.role == 'admin':
        return Customer.query.order_by(Customer.name).all()

    my_customer_ids = set()
    for member in user.projects:
        if member.project.customer_id:
            my_customer_ids.add(member.project.customer_id)

    unassigned = Customer.query.filter(
        ~Customer.id.in_(
            db.session.query(Project.customer_id)
            .filter(Project.customer_id.isnot(None))
        )
    ).all()

    assigned = Customer.query.filter(Customer.id.in_(my_customer_ids)).all() if my_customer_ids else []
    return sorted(set(assigned + unassigned), key=lambda c: c.name.lower())


# ============================================================
#  НЕПРОЧИТАННЫЕ СООБЩЕНИЯ
# ============================================================

def get_unread_counts(user):
    if user.role == 'admin':
        projects = Project.query.filter_by(is_active=True).all()
    else:
        projects = [m.project for m in user.projects]

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
    record = MessageRead.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()

    if record:
        record.last_read_at = datetime.utcnow()
    else:
        record = MessageRead(
            user_id=user_id,
            project_id=project_id,
            last_read_at=datetime.utcnow()
        )
        db.session.add(record)

    db.session.commit()


# ============================================================
#  CONTEXT PROCESSORS
# ============================================================

@app.context_processor
def inject_unread_counts():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:
            return {'unread_counts': get_unread_counts(user)}
    return {'unread_counts': {}}


@app.context_processor
def inject_overdue_count():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:
            overdue_count = Task.query.filter_by(assigned_to=user.id)\
                .filter(Task.status != 'completed')\
                .filter(Task.due_date < datetime.utcnow()).count()
            return {'my_overdue_count': overdue_count}
    return {'my_overdue_count': 0}


# ============================================================
#  СТАТИСТИКА ПО TO-DO
# ============================================================

def get_todo_stats(project_id):
    """Статистика To-Do по проекту"""
    todos = Todo.query.filter_by(project_id=project_id).all()

    return {
        'total': len(todos),
        'done': sum(1 for t in todos if t.is_done),
        'overdue': sum(1 for t in todos if t.is_overdue),
        'new': sum(1 for t in todos if not t.is_done and not t.is_overdue),
        'todos': todos
    }


# ============================================================
#  РАСЧЁТ СТАТИСТИКИ ДЛЯ PDF
# ============================================================

def calculate_project_stats(project):
    tasks = Task.query.filter_by(project_id=project.id, parent_task_id=None).all()
    all_tasks = Task.query.filter_by(project_id=project.id).all()
    milestones = Milestone.query.filter_by(project_id=project.id)\
        .order_by(Milestone.order_index).all()
    reports = Report.query.filter_by(project_id=project.id)\
        .order_by(Report.created_at.desc()).all()
    todos = Todo.query.filter_by(project_id=project.id).all()

    completed_tasks = [t for t in tasks if t.status == 'completed']
    in_progress_tasks = [t for t in tasks if t.status == 'in_progress']
    overdue_tasks = [t for t in tasks if t.is_overdue]
    new_tasks = [t for t in tasks if t.status == 'new' and not t.is_overdue]

    completed_milestones = [m for m in milestones if m.is_completed]
    overdue_milestones = [m for m in milestones if m.is_overdue]

    on_time_reports = [r for r in reports if r.reason == 'on_track']
    delayed_reports = [r for r in reports if r.reason != 'on_track']

    # To-Do статистика
    todo_stats = get_todo_stats(project.id)

    return {
        'tasks': tasks,
        'milestones': milestones,
        'reports': reports,
        'todos': todos,
        'completed_tasks_list': completed_tasks,
        'in_progress_tasks_list': in_progress_tasks,
        'overdue_tasks_list': overdue_tasks,
        'new_tasks_list': new_tasks,
        'total_tasks': len(tasks),
        'total_subtasks': len(all_tasks) - len(tasks),
        'completed_tasks': len(completed_tasks),
        'in_progress_tasks': len(in_progress_tasks),
        'overdue_tasks': len(overdue_tasks),
        'new_tasks': len(new_tasks),
        'total_milestones': len(milestones),
        'completed_milestones': len(completed_milestones),
        'overdue_milestones': len(overdue_milestones),
        'total_reports': len(reports),
        'on_time_reports': len(on_time_reports),
        'delayed_reports': len(delayed_reports),
        'total_todos': len(todos),
        'completed_todos': len([t for t in todos if t.is_done]),
        'todo_total': todo_stats['total'],
        'todo_done': todo_stats['done'],
        'todo_overdue': todo_stats['overdue'],
        'todo_new': todo_stats['new'],
        'completion_percentage': project.completion_percentage,
    }


def calculate_task_stats(task):
    """Статистика по задаче и её подзадачам"""
    subtasks = Task.query.filter_by(parent_task_id=task.id).all()

    done = [t for t in subtasks if t.status == 'completed']
    overdue = [t for t in subtasks if t.is_overdue]
    in_progress = [t for t in subtasks if t.status == 'in_progress']
    new = [t for t in subtasks if t.status == 'new' and not t.is_overdue]

    return {
        'subtasks': subtasks,
        'total': len(subtasks),
        'done': len(done),
        'overdue': len(overdue),
        'in_progress': len(in_progress),
        'new': len(new),
        'done_list': done,
        'overdue_list': overdue,
        'in_progress_list': in_progress,
        'new_list': new,
    }


def calculate_employee_stats(project, user):
    tasks = Task.query.filter_by(project_id=project.id, assigned_to=user.id).all()
    subtasks = [t for t in tasks if t.parent_task_id]

    todos = Todo.query.filter_by(project_id=project.id, assigned_to=user.id).all()
    messages = Message.query.filter_by(project_id=project.id, user_id=user.id).all()
    reports = Report.query.filter_by(project_id=project.id, author_id=user.id).all()

    completed_tasks = [t for t in tasks if t.status == 'completed']
    in_progress_tasks = [t for t in tasks if t.status == 'in_progress']
    overdue_tasks = [t for t in tasks if t.is_overdue]

    activity_score = (
        len(messages) * 1 +
        len(completed_tasks) * 5 +
        len(in_progress_tasks) * 3 +
        len(todos) * 1 +
        len(reports) * 3
    )

    member = ProjectMember.query.filter_by(
        user_id=user.id, project_id=project.id
    ).first()

    total_tasks = len(tasks)
    completion_rate = (len(completed_tasks) / total_tasks * 100) if total_tasks else 0
    overdue_rate = (len(overdue_tasks) / total_tasks * 100) if total_tasks else 0

    return {
        'total_tasks': total_tasks,
        'completed_tasks': len(completed_tasks),
        'in_progress_tasks': len(in_progress_tasks),
        'overdue_tasks': len(overdue_tasks),
        'total_subtasks': len(subtasks),
        'total_todos': len(todos),
        'completed_todos': len([t for t in todos if t.is_done]),
        'total_messages': len(messages),
        'total_reports': len(reports),
        'activity_score': activity_score,
        'completion_rate': round(completion_rate, 1),
        'overdue_rate': round(overdue_rate, 1),
        'role_in_project': member.role_display if member else 'Не в проекте',
        'tasks': tasks,
        'todos': todos,
        'messages': messages,
        'reports': reports,
    }


def generate_pdf_response(html_content, filename):
    if not WEASYPRINT_AVAILABLE:
        flash('WeasyPrint не установлен.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))

    pdf_bytes = HTML(string=html_content, base_url=request.url_root).write_pdf()

    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================
#  EMAIL-УВЕДОМЛЕНИЯ
# ============================================================

def send_deadline_email(task, recipient, days_left, role='assignee'):
    if not FLASK_MAIL_AVAILABLE or mail is None:
        return False
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        return False

    try:
        project = task.project
        leader = project.creator

        if days_left == 0:
            urgency = "🔴 СЕГОДНЯ"
            days_text = "сегодня"
        elif days_left == 1:
            urgency = "🟠 ЗАВТРА"
            days_text = "завтра"
        else:
            urgency = f"🟡 через {days_left} дн."
            days_text = f"через {days_left} дн."

        if role == 'leader':
            subject = f"⚠️ [Руководителю] Дедлайн {days_text}: {task.title}"
            greeting = f"Здравствуйте, {recipient.first_name}!"
            intro = (f"Напоминаем как руководителю проекта <strong>«{project.name}»</strong>: "
                     f"{days_text} истекает дедлайн задачи.")
        else:
            subject = f"⚠️ Дедлайн {days_text}: {task.title}"
            greeting = f"Здравствуйте, {recipient.first_name}!"
            intro = f"Напоминаем: {days_text} истекает дедлайн вашей задачи."

        status_names = {'new': '🆕 Новая', 'in_progress': '🔄 В работе', 'completed': '✅ Завершена'}
        status_display = status_names.get(task.status, task.status)

        assignee_name = (task.assignee.first_name + ' ' + task.assignee.last_name) if task.assignee else '—'
        leader_name = (leader.first_name + ' ' + leader.last_name) if leader else '—'
        milestone_name = task.milestone.name if task.milestone else None
        description = task.description or ''

        html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, Helvetica, sans-serif; background: #f5f7fb; margin: 0; padding: 20px;">
<div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
    <div style="background: linear-gradient(135deg, #4f46e5, #6366f1); padding: 24px; color: white;">
        <h1 style="margin: 0; font-size: 20px;">⚠️ Напоминание о дедлайне</h1>
        <p style="margin: 8px 0 0; opacity: 0.9; font-size: 14px;">Система Workspace</p>
    </div>
    <div style="padding: 24px;">
        <p style="font-size: 15px; color: #1a1a2e;">{greeting}</p>
        <p style="font-size: 15px; color: #1a1a2e;">{intro}</p>
        <p style="font-size: 22px; font-weight: bold; color: #dc2626; text-align: center; margin: 20px 0;">{urgency}</p>
        <div style="background: #f8f9fa; border-radius: 8px; padding: 16px; margin: 20px 0; border-left: 4px solid #4f46e5;">
            <h3 style="margin: 0 0 12px; font-size: 16px; color: #1a1a2e;">{task.title}</h3>
            <table style="width: 100%; font-size: 14px; color: #374151;">
                <tr><td style="padding: 4px 0; width: 140px;"><strong>Проект:</strong></td><td>{project.name}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Дедлайн:</strong></td><td style="color: #dc2626; font-weight: bold;">{task.due_date.strftime('%d.%m.%Y')}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Статус:</strong></td><td>{status_display}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Исполнитель:</strong></td><td>{assignee_name}</td></tr>
                <tr><td style="padding: 4px 0;"><strong>Руководитель:</strong></td><td>{leader_name}</td></tr>
                {f'<tr><td style="padding: 4px 0;"><strong>Веха:</strong></td><td>{milestone_name}</td></tr>' if milestone_name else ''}
            </table>
            {f'<p style="margin: 12px 0 0; font-size: 13px; color: #6b7280;"><strong>Описание:</strong> {description}</p>' if description else ''}
        </div>
        <div style="text-align: center; margin: 24px 0;">
            <a href="http://84.201.178.247/task/{task.id}" style="background: #4f46e5; color: white; padding: 12px 28px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 15px;">Открыть задачу</a>
        </div>
    </div>
    <div style="background: #f8f9fa; padding: 16px 24px; text-align: center; border-top: 1px solid #e5e7eb;">
        <p style="margin: 0; font-size: 12px; color: #6b7280;">Это автоматическое уведомление от системы Workspace.</p>
    </div>
</div>
</body>
</html>"""

        msg = MailMessage(subject, recipients=[recipient.email], html=html_body)
        mail.send(msg)
        print(f"✅ Email отправлен на {recipient.email} ({role}) по задаче «{task.title}» ({days_left} дн.)")
        return True

    except Exception as e:
        print(f"❌ Ошибка отправки email на {recipient.email}: {e}")
        return False


def check_and_send_deadline_notifications(days_before=(3, 1, 0)):
    print(f"\n🔍 Проверка дедлайнов: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}")
    now = datetime.utcnow()
    sent_count = 0

    tasks = Task.query.filter(
        Task.due_date.isnot(None),
        Task.status.in_(['new', 'in_progress'])
    ).all()

    for task in tasks:
        days_left = (task.due_date.date() - now.date()).days
        if days_left not in days_before:
            continue

        recipients = []
        if task.assignee and task.assignee.email:
            recipients.append((task.assignee, 'assignee'))

        leader = task.project.creator
        if leader and leader.email:
            if not task.assignee or leader.id != task.assignee.id:
                recipients.append((leader, 'leader'))

        for recipient, role in recipients:
            if send_deadline_email(task, recipient, days_left, role):
                sent_count += 1

    print(f"📧 Отправлено уведомлений: {sent_count}\n")
    return sent_count


# ============================================================
#  АУТЕНТИФИКАЦИЯ
# ============================================================

@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    token = request.args.get('token')
    invitation = None
    if token:
        invitation = Invitation.query.filter_by(token=token, is_used=False).first()
        if not invitation or invitation.expires_at < datetime.utcnow():
            flash('Приглашение недействительно или истекло.', 'danger')
            return redirect(url_for('login'))

    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        company = request.form['company']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует.', 'danger')
            return redirect(url_for('register'))

        new_user = User(
            first_name=first_name, last_name=last_name,
            company=company, email=email, password=password, role='user'
        )
        db.session.add(new_user)
        db.session.commit()

        if invitation and invitation.email == email:
            db.session.add(ProjectMember(
                user_id=new_user.id,
                project_id=invitation.project_id,
                role_in_project=invitation.role
            ))
            invitation.is_used = True
            db.session.commit()
            flash('Вы зарегистрированы и добавлены в проект!', 'success')
        else:
            flash('Регистрация успешна! Теперь можете создать свой проект.', 'success')

        return redirect(url_for('login'))

    return render_template('register.html', invitation=invitation)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(
            email=request.form['email'],
            password=request.form['password']
        ).first()
        if user:
            session['user_id'] = user.id
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['user_role'] = user.role
            flash(f'Добро пожаловать, {user.first_name}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Неверный email или пароль.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('login'))


# ============================================================
#  ДАШБОРД
# ============================================================

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session['user_id'])
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

    return render_template('dashboard.html',
                           projects=filtered,
                           all_projects=projects,
                           customers=customers,
                           user=user,
                           filter_customer=filter_customer,
                           filter_start_from=filter_start_from,
                           filter_start_to=filter_start_to,
                           filter_status=filter_status)


# ============================================================
#  МОИ ЗАДАЧИ
# ============================================================

@app.route('/my-tasks')
@login_required
def my_tasks():
    user = db.session.get(User, session['user_id'])

    all_my_tasks = Task.query.filter_by(assigned_to=user.id)\
        .order_by(Task.due_date.asc().nullslast(), Task.status).all()

    active = [t for t in all_my_tasks if t.status in ('new', 'in_progress')]
    overdue = [t for t in all_my_tasks if t.is_overdue]
    completed = [t for t in all_my_tasks if t.status == 'completed']

    now = datetime.utcnow()
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
                           now=now)


@app.route('/user/<int:user_id>/all-tasks')
@login_required
def user_all_tasks(user_id):
    current_user = db.session.get(User, session['user_id'])
    employee = db.session.get(User, user_id)

    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('dashboard'))

    is_allowed = False
    if current_user.role == 'admin':
        is_allowed = True
    else:
        employee_projects = [m.project_id for m in employee.projects]
        managed_projects = []
        for m in current_user.projects:
            if m.role_in_project in ('admin', 'manager'):
                managed_projects.append(m.project_id)
        if set(employee_projects) & set(managed_projects):
            is_allowed = True

    if not is_allowed:
        flash('У вас нет прав.', 'danger')
        return redirect(url_for('dashboard'))

    all_tasks = Task.query.filter_by(assigned_to=user_id)\
        .order_by(Task.due_date.asc().nullslast(), Task.status).all()

    active = [t for t in all_tasks if t.status in ('new', 'in_progress')]
    overdue = [t for t in all_tasks if t.is_overdue]
    completed = [t for t in all_tasks if t.status == 'completed']

    now = datetime.utcnow()
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
#  МОЙ КАЛЕНДАРЬ
# ============================================================

@app.route('/my-calendar')
@login_required
def my_calendar():
    user = db.session.get(User, session['user_id'])

    personal_events = Event.query.filter_by(
        event_type='personal', owner_id=user.id
    ).order_by(Event.start_time).all()

    projects = get_user_projects(user)
    project_ids = [p.id for p in projects]

    project_events = Event.query.filter(
        Event.event_type == 'project',
        Event.project_id.in_(project_ids)
    ).order_by(Event.start_time).all() if project_ids else []

    return render_template('my_calendar.html',
                           user=user,
                           personal_events=personal_events,
                           project_events=project_events,
                           projects=projects,
                           now=datetime.utcnow())


@app.route('/my-calendar/events.json')
@login_required
def my_calendar_json():
    user = db.session.get(User, session['user_id'])
    events = []

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

    projects = get_user_projects(user)
    project_ids = [p.id for p in projects]

    if project_ids:
        for e in Event.query.filter(
            Event.event_type == 'project',
            Event.project_id.in_(project_ids)
        ).all():
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

    tasks = Task.query.filter_by(assigned_to=user.id)\
        .filter(Task.due_date.isnot(None)).all()

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
            'url': url_for('view_task', task_id=t.id),
            'extendedProps': {
                'type': 'task',
                'project': t.project.name if t.project else ''
            }
        })

    return jsonify(events)


# ============================================================
#  ЗАКАЗЧИКИ
# ============================================================

@app.route('/customers')
@login_required
def customers_list():
    user = db.session.get(User, session['user_id'])
    customers = get_available_customers(user)
    return render_template('customers.html',
                           customers=customers,
                           user=user,
                           projects=get_user_projects(user))


@app.route('/customer/create', methods=['GET', 'POST'])
@login_required
def create_customer():
    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        customer = Customer(
            name=request.form['name'],
            inn=request.form.get('inn'),
            contact_person=request.form.get('contact_person'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
        )
        db.session.add(customer)
        db.session.commit()
        flash('Заказчик добавлен!', 'success')

        next_url = request.form.get('next') or request.referrer or url_for('customers_list')
        return redirect(next_url)

    return render_template('create_customer.html',
                           user=user,
                           projects=get_user_projects(user))


@app.route('/customer/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    user = db.session.get(User, session['user_id'])
    customer = Customer.query.get_or_404(customer_id)

    can_edit = False
    if user.role == 'admin':
        can_edit = True
    else:
        for member in user.projects:
            if member.project.customer_id == customer_id:
                can_edit = True
                break
        if not Project.query.filter_by(customer_id=customer_id).first():
            can_edit = True

    if not can_edit:
        flash('У вас нет прав на редактирование этого заказчика.', 'danger')
        return redirect(url_for('customers_list'))

    if request.method == 'POST':
        customer.name = request.form['name']
        customer.inn = request.form.get('inn')
        customer.contact_person = request.form.get('contact_person')
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        customer.address = request.form.get('address')
        db.session.commit()
        flash('Заказчик обновлён!', 'success')
        return redirect(url_for('customers_list'))

    return render_template('edit_customer.html',
                           customer=customer,
                           user=user,
                           projects=get_user_projects(user))


# ============================================================
#  ПРОЕКТЫ
# ============================================================

@app.route('/project/create', methods=['GET', 'POST'])
@login_required
def create_project():
    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        start_date = None
        if request.form.get('start_date'):
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        end_date = None
        if request.form.get('end_date'):
            end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')

        customer_id = request.form.get('customer_id') or None

        project = Project(
            name=request.form['name'],
            description=request.form['description'],
            created_by=session['user_id'],
            customer_id=int(customer_id) if customer_id else None,
            start_date=start_date or datetime.utcnow(),
            end_date=end_date,
        )
        db.session.add(project)
        db.session.commit()

        db.session.add(ProjectMember(
            user_id=session['user_id'],
            project_id=project.id,
            role_in_project='admin'
        ))
        db.session.commit()

        flash('Проект создан! Вы назначены руководителем.', 'success')
        return redirect(url_for('view_project', project_id=project.id))

    customers = get_available_customers(user)
    return render_template('create_project.html',
                           customers=customers,
                           user=user,
                           projects=get_user_projects(user))


@app.route('/project/<int:project_id>')
@login_required
def view_project(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа к этому проекту.', 'danger')
        return redirect(url_for('dashboard'))

    project = Project.query.get_or_404(project_id)
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(project_id)

    if request.args.get('mark_read') == '1':
        mark_project_as_read(user.id, project_id)

    members = ProjectMember.query.filter_by(project_id=project.id).all()
    tasks = Task.query.filter_by(project_id=project.id, parent_task_id=None).all()
    messages = Message.query.filter_by(project_id=project.id).order_by(Message.created_at.asc()).all()
    folders = Folder.query.filter_by(project_id=project.id, parent_folder_id=None).all()
    files = File.query.filter_by(project_id=project.id, folder_id=None, task_id=None).all()
    all_users = User.query.filter(User.role != 'admin').all()

    milestones = Milestone.query.filter_by(project_id=project.id)\
        .order_by(Milestone.order_index).all()
    todos = Todo.query.filter_by(project_id=project.id)\
        .order_by(Todo.is_done, Todo.created_at.desc()).all()
    reports = Report.query.filter_by(project_id=project.id)\
        .order_by(Report.created_at.desc()).all()
    events = Event.query.filter_by(project_id=project.id, event_type='project')\
        .order_by(Event.start_time).all()

    overdue_milestones = [m for m in milestones if m.is_overdue]
    overdue_tasks = [t for t in tasks if t.is_overdue]

    project_overdue = project.is_overdue
    project_days_overdue = project.days_overdue

    # To-Do статистика
    todo_stats = get_todo_stats(project.id)

    return render_template('project.html',
                           project=project,
                           members=members,
                           tasks=tasks,
                           messages=messages,
                           folders=folders,
                           files=files,
                           all_users=all_users,
                           user=user,
                           user_role=user_role,
                           milestones=milestones,
                           todos=todos,
                           reports=reports,
                           events=events,
                           now=datetime.utcnow(),
                           projects=get_user_projects(user),
                           can_manage=can_manage_project(project_id),
                           overdue_milestones=overdue_milestones,
                           overdue_tasks=overdue_tasks,
                           project_overdue=project_overdue,
                           project_days_overdue=project_days_overdue,
                           todo_stats=todo_stats)


@app.route('/project/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    if not can_manage_project(project_id):
        flash('Только руководитель может редактировать проект.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    project = Project.query.get_or_404(project_id)
    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        project.name = request.form['name']
        project.description = request.form.get('description', '')
        project.status = request.form.get('status', 'active')

        customer_id = request.form.get('customer_id') or None
        project.customer_id = int(customer_id) if customer_id else None

        if request.form.get('start_date'):
            project.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
        else:
            project.start_date = None

        if request.form.get('end_date'):
            project.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
        else:
            project.end_date = None

        db.session.commit()
        flash('Проект обновлён!', 'success')
        return redirect(url_for('view_project', project_id=project.id))

    customers = get_available_customers(user)
    return render_template('edit_project.html',
                           project=project,
                           customers=customers,
                           user=user,
                           user_role=get_user_role_in_project(project_id),
                           projects=get_user_projects(user))


@app.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    user = db.session.get(User, session['user_id'])
    project = Project.query.get_or_404(project_id)

    is_allowed = False
    if user.role == 'admin':
        is_allowed = True
    else:
        member = ProjectMember.query.filter_by(
            user_id=user.id, project_id=project_id
        ).first()
        if member and member.role_in_project == 'admin':
            is_allowed = True

    if not is_allowed:
        flash('Только руководитель проекта может его удалить.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    confirm_text = request.form.get('confirm_text', '').strip().upper()
    if confirm_text != 'УДАЛИТЬ':
        flash('Введите слово УДАЛИТЬ для подтверждения.', 'warning')
        return redirect(url_for('view_project', project_id=project_id))

    project_name = project.name

    for file in File.query.filter_by(project_id=project_id).all():
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.stored_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    for task in Task.query.filter_by(project_id=project_id).all():
        for sub in Task.query.filter_by(parent_task_id=task.id).all():
            db.session.delete(sub)

    db.session.delete(project)
    db.session.commit()

    flash(f'Проект «{project_name}» удалён.', 'success')
    return redirect(url_for('dashboard'))


# ============================================================
#  PDF-ОТЧЁТЫ
# ============================================================

@app.route('/project/<int:project_id>/report/pdf')
@login_required
def project_report_pdf(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    project = Project.query.get_or_404(project_id)
    user = db.session.get(User, session['user_id'])
    stats = calculate_project_stats(project)

    html_content = render_template(
        'pdf/project_report.html',
        project=project,
        stats=stats,
        user=user,
        now=datetime.utcnow()
    )

    filename = f"project_{project.id}_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return generate_pdf_response(html_content, filename)


@app.route('/task/<int:task_id>/report/pdf')
@login_required
def task_report_pdf(task_id):
    """PDF-отчёт по одной задаче"""
    task = Task.query.get_or_404(task_id)
    if not check_project_access(task.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    user = db.session.get(User, session['user_id'])
    stats = calculate_task_stats(task)

    html_content = render_template(
        'pdf/task_report.html',
        task=task,
        stats=stats,
        user=user,
        now=datetime.utcnow()
    )

    filename = f"task_{task.id}_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return generate_pdf_response(html_content, filename)


@app.route('/project/<int:project_id>/employee/<int:user_id>/pdf')
@login_required
def employee_report_pdf(project_id, user_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    project = Project.query.get_or_404(project_id)
    employee = db.session.get(User, user_id)
    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    member = ProjectMember.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()
    if not member:
        flash('Сотрудник не участвует в этом проекте.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    current_user = db.session.get(User, session['user_id'])
    stats = calculate_employee_stats(project, employee)

    html_content = render_template(
        'pdf/employee_report.html',
        project=project,
        employee=employee,
        member=member,
        stats=stats,
        user=current_user,
        now=datetime.utcnow()
    )

    filename = f"employee_{employee.last_name}_{employee.id}_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return generate_pdf_response(html_content, filename)


@app.route('/project/<int:project_id>/employee/<int:user_id>/report')
@login_required
def employee_report_view(project_id, user_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    project = Project.query.get_or_404(project_id)
    employee = db.session.get(User, user_id)
    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    member = ProjectMember.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()
    if not member:
        flash('Сотрудник не участвует в этом проекте.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    user = db.session.get(User, session['user_id'])
    stats = calculate_employee_stats(project, employee)

    return render_template(
        'employee_report.html',
        project=project,
        employee=employee,
        member=member,
        stats=stats,
        user=user,
        now=datetime.utcnow(),
        projects=get_user_projects(user)
    )


# ============================================================
#  СОБЫТИЯ (КАЛЕНДАРЬ)
# ============================================================

@app.route('/project/<int:project_id>/event/create', methods=['POST'])
@login_required
def create_event(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    if not can_manage_project(project_id):
        flash('Только руководитель может создавать события проекта.', 'danger')
        return redirect(url_for('view_project', project_id=project_id) + '#calendar')

    title = request.form['title']
    description = request.form.get('description', '')
    start_str = request.form.get('start_time')
    end_str = request.form.get('end_time')
    all_day = request.form.get('all_day') == 'on'
    color = request.form.get('color', 'blue')

    if not start_str:
        flash('Укажите дату события.', 'warning')
        return redirect(url_for('view_project', project_id=project_id) + '#calendar')

    if all_day:
        start_time = datetime.strptime(start_str, '%Y-%m-%d')
        end_time = None
    else:
        start_time = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        end_time = None
        if end_str:
            end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')

    db.session.add(Event(
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        color=color,
        project_id=project_id,
        created_by=session['user_id'],
        event_type='project'
    ))
    db.session.commit()
    flash('Событие проекта создано!', 'success')
    return redirect(url_for('view_project', project_id=project_id) + '#calendar')


@app.route('/personal-event/create', methods=['POST'])
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
        return redirect(request.referrer or url_for('my_calendar'))

    if all_day:
        start_time = datetime.strptime(start_str, '%Y-%m-%d')
        end_time = None
    else:
        start_time = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        end_time = None
        if end_str:
            end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')

    db.session.add(Event(
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
    ))
    db.session.commit()
    flash('Личное событие создано!', 'success')
    return redirect(url_for('my_calendar'))


@app.route('/event/<int:event_id>/delete', methods=['POST'])
@login_required
def delete_event(event_id):
    e = Event.query.get_or_404(event_id)
    user = db.session.get(User, session['user_id'])

    if e.event_type == 'personal':
        if e.owner_id != user.id:
            flash('Нет прав.', 'danger')
            return redirect(request.referrer or url_for('dashboard'))
        db.session.delete(e)
        db.session.commit()
        flash('Личное событие удалено.', 'info')
        return redirect(url_for('my_calendar'))
    else:
        if not can_manage_project(e.project_id) and e.created_by != user.id:
            flash('Нет прав.', 'danger')
            return redirect(url_for('view_project', project_id=e.project_id))
        pid = e.project_id
        db.session.delete(e)
        db.session.commit()
        flash('Событие удалено.', 'info')
        return redirect(url_for('view_project', project_id=pid) + '#calendar')


@app.route('/project/<int:project_id>/events.json')
@login_required
def events_json(project_id):
    if not check_project_access(project_id):
        return jsonify([])

    user = db.session.get(User, session['user_id'])
    events = []

    for e in Event.query.filter_by(project_id=project_id, event_type='project').all():
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

    tasks = Task.query.filter_by(project_id=project_id)\
        .filter(Task.due_date.isnot(None)).all()

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
            'url': url_for('view_task', task_id=t.id),
            'extendedProps': {
                'type': 'task',
                'assignee': f"{t.assignee.first_name} {t.assignee.last_name}" if t.assignee else 'Не назначена',
                'status': t.status
            }
        })

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

    return jsonify(events)


# ============================================================
#  ВЕХИ
# ============================================================

@app.route('/project/<int:project_id>/milestone/create', methods=['POST'])
@login_required
def create_milestone(project_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

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
    return redirect(url_for('view_project', project_id=project_id))


@app.route('/milestone/<int:milestone_id>/toggle', methods=['POST'])
@login_required
def toggle_milestone(milestone_id):
    m = Milestone.query.get_or_404(milestone_id)
    if not can_manage_project(m.project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=m.project_id))

    m.is_completed = not m.is_completed
    m.completed_at = datetime.utcnow() if m.is_completed else None
    db.session.commit()
    flash('Веха обновлена.', 'success')
    return redirect(url_for('view_project', project_id=m.project_id))


@app.route('/milestone/<int:milestone_id>/delete', methods=['POST'])
@login_required
def delete_milestone(milestone_id):
    m = Milestone.query.get_or_404(milestone_id)
    pid = m.project_id
    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=pid))

    db.session.delete(m)
    db.session.commit()
    flash('Веха удалена.', 'info')
    return redirect(url_for('view_project', project_id=pid))


# ============================================================
#  TO-DO
# ============================================================

@app.route('/project/<int:project_id>/todo/create', methods=['POST'])
@login_required
def create_todo(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    assigned = request.form.get('assigned_to')
    due_str = request.form.get('due_date')
    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(due_str, '%Y-%m-%d')
        except ValueError:
            pass

    db.session.add(Todo(
        title=request.form['title'],
        project_id=project_id,
        assigned_to=int(assigned) if assigned else None,
        created_by=session['user_id'],
        due_date=due_date
    ))
    db.session.commit()
    flash('Задача добавлена в To-Do!', 'success')
    return redirect(url_for('view_project', project_id=project_id) + '#todo')


@app.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    t = Todo.query.get_or_404(todo_id)
    if not check_project_access(t.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    t.is_done = not t.is_done
    t.done_at = datetime.utcnow() if t.is_done else None
    db.session.commit()
    return redirect(request.referrer or url_for('view_project', project_id=t.project_id) + '#todo')


@app.route('/todo/<int:todo_id>/comment', methods=['POST'])
@login_required
def update_todo_comment(todo_id):
    """Обновление комментария к To-Do (причина просрочки)"""
    t = Todo.query.get_or_404(todo_id)
    if not check_project_access(t.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    t.comment = request.form.get('comment', '')
    db.session.commit()
    flash('Комментарий сохранён.', 'success')
    return redirect(request.referrer or url_for('view_project', project_id=t.project_id) + '#todo')


@app.route('/todo/<int:todo_id>/delete', methods=['POST'])
@login_required
def delete_todo(todo_id):
    t = Todo.query.get_or_404(todo_id)
    pid = t.project_id
    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=pid))
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for('view_project', project_id=pid) + '#todo')


# ============================================================
#  ОТЧЁТЫ
# ============================================================

@app.route('/project/<int:project_id>/report/create', methods=['POST'])
@login_required
def create_report(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    milestone_id = request.form.get('milestone_id') or None
    delay = request.form.get('delay_days', '0')

    report = Report(
        title=request.form['title'],
        content=request.form.get('content', ''),
        project_id=project_id,
        milestone_id=int(milestone_id) if milestone_id else None,
        author_id=session['user_id'],
        reason=request.form.get('reason', 'on_track'),
        reason_detail=request.form.get('reason_detail', ''),
        delay_days=int(delay) if delay and delay.isdigit() else 0,
    )
    db.session.add(report)
    db.session.commit()
    flash('Отчёт создан!', 'success')
    return redirect(url_for('view_project', project_id=project_id) + '#reports')


@app.route('/report/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    r = Report.query.get_or_404(report_id)
    pid = r.project_id
    if not can_manage_project(pid) and r.author_id != session['user_id']:
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=pid))
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for('view_project', project_id=pid) + '#reports')


# ============================================================
#  КОМАНДА ПРОЕКТА
# ============================================================

@app.route('/project/<int:project_id>/settings')
@login_required
def project_settings(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(project_id)

    if not can_manage_project(project_id):
        flash('Только руководитель может управлять настройками.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    project = Project.query.get_or_404(project_id)
    members = ProjectMember.query.filter_by(project_id=project.id).all()

    return render_template('project_settings.html',
                           project=project,
                           members=members,
                           user=user,
                           user_role=user_role,
                           projects=get_user_projects(user))


@app.route('/project/<int:project_id>/invite', methods=['POST'])
@login_required
def invite_user(project_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))

    email = request.form['email']
    role = request.form.get('role', 'member')

    existing_user = User.query.filter_by(email=email).first()

    if existing_user:
        if ProjectMember.query.filter_by(user_id=existing_user.id, project_id=project_id).first():
            flash('Уже в проекте.', 'warning')
            return redirect(url_for('project_settings', project_id=project_id))
        db.session.add(ProjectMember(
            user_id=existing_user.id, project_id=project_id, role_in_project=role
        ))
        db.session.commit()
        flash(f'{existing_user.first_name} добавлен!', 'success')
    else:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow().replace(day=datetime.utcnow().day + 7)
        db.session.add(Invitation(
            email=email, project_id=project_id, invited_by=session['user_id'],
            role=role, token=token, expires_at=expires_at
        ))
        db.session.commit()
        link = url_for('register', token=token, _external=True)
        flash(f'Ссылка для регистрации: {link}', 'success')

    return redirect(url_for('project_settings', project_id=project_id))


@app.route('/project/<int:project_id>/member/<int:member_id>/remove', methods=['POST'])
@login_required
def remove_member(project_id, member_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))
    member = ProjectMember.query.get_or_404(member_id)
    if member.user_id == Project.query.get(project_id).created_by:
        flash('Нельзя удалить создателя.', 'danger')
        return redirect(url_for('project_settings', project_id=project_id))
    db.session.delete(member)
    db.session.commit()
    flash('Участник удалён.', 'info')
    return redirect(url_for('project_settings', project_id=project_id))


@app.route('/project/<int:project_id>/member/<int:member_id>/change_role', methods=['POST'])
@login_required
def change_member_role(project_id, member_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))
    member = ProjectMember.query.get_or_404(member_id)
    if member.user_id == Project.query.get(project_id).created_by:
        flash('Нельзя менять роль создателя.', 'danger')
        return redirect(url_for('project_settings', project_id=project_id))
    member.role_in_project = request.form['role']
    db.session.commit()
    flash('Роль изменена.', 'success')
    return redirect(url_for('project_settings', project_id=project_id))


# ============================================================
#  ЗАДАЧИ
# ============================================================

@app.route('/project/<int:project_id>/task/create', methods=['POST'])
@login_required
def create_task(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    due_date = None
    if request.form.get('due_date'):
        due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d')

    assigned = request.form.get('assigned_to')
    parent_task_id = request.form.get('parent_task_id')
    milestone_id = request.form.get('milestone_id')

    task = Task(
        title=request.form['title'],
        description=request.form.get('description', ''),
        project_id=project_id,
        assigned_to=int(assigned) if assigned else None,
        due_date=due_date,
        created_by=session['user_id'],
        parent_task_id=int(parent_task_id) if parent_task_id else None,
        milestone_id=int(milestone_id) if milestone_id else None,
    )
    db.session.add(task)
    db.session.commit()
    flash('Задача создана!', 'success')

    if parent_task_id:
        return redirect(url_for('view_task', task_id=parent_task_id))
    return redirect(url_for('view_project', project_id=project_id))


@app.route('/task/<int:task_id>')
@login_required
def view_task(task_id):
    task = Task.query.get_or_404(task_id)
    if not check_project_access(task.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(task.project_id)

    files = File.query.filter_by(task_id=task.id).all()
    subtasks = Task.query.filter_by(parent_task_id=task.id).all()
    all_users = User.query.filter(User.role != 'admin').all()
    milestones = Milestone.query.filter_by(project_id=task.project_id).all()

    # Статистика по задаче
    task_stats = calculate_task_stats(task)

    return render_template('task_detail.html',
                           task=task,
                           files=files,
                           subtasks=subtasks,
                           all_users=all_users,
                           milestones=milestones,
                           user=user,
                           user_role=user_role,
                           now=datetime.utcnow(),
                           projects=get_user_projects(user),
                           can_manage=can_manage_project(task.project_id),
                           task_stats=task_stats)


@app.route('/task/<int:task_id>/comment', methods=['POST'])
@login_required
def update_task_comment(task_id):
    """Обновление комментария к задаче (причина просрочки)"""
    task = Task.query.get_or_404(task_id)
    user = db.session.get(User, session['user_id'])

    if not check_project_access(task.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))

    role = get_user_role_in_project(task.project_id)
    if role not in ['admin', 'manager'] and task.assigned_to != user.id:
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_task', task_id=task_id))

    task.comment = request.form.get('comment', '')
    db.session.commit()
    flash('Комментарий сохранён.', 'success')
    return redirect(url_for('view_task', task_id=task_id))


@app.route('/task/<int:task_id>/update_status', methods=['POST'])
@login_required
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    user = db.session.get(User, session['user_id'])

    if not can_manage_project(task.project_id) and task.assigned_to != user.id:
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=task.project_id))

    task.status = request.form['status']
    db.session.commit()
    flash('Статус обновлён!', 'success')
    return redirect(request.referrer or url_for('view_project', project_id=task.project_id))


@app.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    pid = task.project_id
    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=pid))
    for st in task.subtasks:
        db.session.delete(st)
    db.session.delete(task)
    db.session.commit()
    flash('Задача удалена.', 'info')
    return redirect(url_for('view_project', project_id=pid))


# ============================================================
#  ПАПКИ И ФАЙЛЫ
# ============================================================

@app.route('/project/<int:project_id>/folder/create', methods=['POST'])
@login_required
def create_folder(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    parent_id = request.form.get('parent_id') or None
    db.session.add(Folder(
        name=request.form['name'],
        project_id=project_id,
        parent_folder_id=int(parent_id) if parent_id else None,
        created_by=session['user_id']
    ))
    db.session.commit()
    flash('Папка создана!', 'success')
    return redirect(request.referrer or url_for('view_project', project_id=project_id))


@app.route('/folder/<int:folder_id>')
@login_required
def view_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if not check_project_access(folder.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    user = db.session.get(User, session['user_id'])
    return render_template('folder.html',
                           folder=folder,
                           subfolders=Folder.query.filter_by(parent_folder_id=folder_id).all(),
                           files=File.query.filter_by(folder_id=folder_id).all(),
                           user=user,
                           user_role=get_user_role_in_project(folder.project_id),
                           projects=get_user_projects(user))


@app.route('/folder/<int:folder_id>/delete', methods=['POST'])
@login_required
def delete_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    pid = folder.project_id
    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=pid))
    for f in folder.files:
        p = os.path.join(app.config['UPLOAD_FOLDER'], f.stored_name)
        if os.path.exists(p):
            os.remove(p)
        db.session.delete(f)
    for sf in folder.subfolders:
        db.session.delete(sf)
    db.session.delete(folder)
    db.session.commit()
    flash('Папка удалена.', 'info')
    return redirect(url_for('view_project', project_id=pid))


@app.route('/project/<int:project_id>/upload', methods=['POST'])
@login_required
def upload_file(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    if 'file' not in request.files or request.files['file'].filename == '':
        flash('Файл не выбран.', 'warning')
        return redirect(request.referrer or url_for('view_project', project_id=project_id))

    file = request.files['file']
    folder_id = request.form.get('folder_id') or None
    task_id = request.form.get('task_id') or None

    ext = os.path.splitext(file.filename)[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
    file.save(path)

    db.session.add(File(
        original_name=file.filename,
        stored_name=stored_name,
        file_size=os.path.getsize(path),
        file_type=file.content_type,
        project_id=project_id,
        folder_id=int(folder_id) if folder_id else None,
        task_id=int(task_id) if task_id else None,
        uploaded_by=session['user_id']
    ))
    db.session.commit()
    flash(f'Файл "{file.filename}" загружен!', 'success')

    if task_id:
        return redirect(url_for('view_task', task_id=int(task_id)))
    if folder_id:
        return redirect(url_for('view_folder', folder_id=int(folder_id)))
    return redirect(url_for('view_project', project_id=project_id))


@app.route('/file/<int:file_id>/download')
@login_required
def download_file(file_id):
    f = File.query.get_or_404(file_id)
    if not check_project_access(f.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    return send_from_directory(app.config['UPLOAD_FOLDER'], f.stored_name, download_name=f.original_name)


@app.route('/file/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(file_id):
    f = File.query.get_or_404(file_id)
    pid = f.project_id
    if not can_manage_project(pid) and f.uploaded_by != session['user_id']:
        flash('Нет прав.', 'danger')
        return redirect(url_for('view_project', project_id=pid))
    p = os.path.join(app.config['UPLOAD_FOLDER'], f.stored_name)
    if os.path.exists(p):
        os.remove(p)
    db.session.delete(f)
    db.session.commit()
    return redirect(request.referrer or url_for('view_project', project_id=pid))


# ============================================================
#  ЧАТ
# ============================================================

@app.route('/project/<int:project_id>/send_message', methods=['POST'])
@login_required
def send_message(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    text = request.form['message']
    if text.strip():
        db.session.add(Message(text=text, user_id=session['user_id'], project_id=project_id))
        db.session.commit()
        mark_project_as_read(session['user_id'], project_id)
    return redirect(url_for('view_project', project_id=project_id) + '#chat')


@app.route('/project/<int:project_id>/mark_read', methods=['POST'])
@login_required
def mark_read(project_id):
    if not check_project_access(project_id):
        return jsonify({'success': False}), 403
    mark_project_as_read(session['user_id'], project_id)
    return jsonify({'success': True})


# ============================================================
#  АДМИН: РУЧНАЯ РАССЫЛКА УВЕДОМЛЕНИЙ
# ============================================================

@app.route('/admin/send-deadline-notifications', methods=['POST'])
@login_required
def manual_send_notifications():
    user = db.session.get(User, session['user_id'])
    if user.role != 'admin':
        flash('Доступ запрещён.', 'danger')
        return redirect(url_for('dashboard'))

    count = check_and_send_deadline_notifications()
    flash(f'Отправлено уведомлений: {count}. Проверьте лог.', 'success')
    return redirect(url_for('dashboard'))


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == '__main__':
    app.run(debug=True, port=5001)