from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from functools import wraps
import os
import uuid
import secrets

app = Flask(__name__)
app.secret_key = 'supersecretkey123'

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'workspace.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- МОДЕЛИ ---

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

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    @property
    def completion_percentage(self):
        tasks = Task.query.filter_by(project_id=self.id, parent_task_id=None).all()
        if not tasks:
            return 0
        completed = sum(1 for t in tasks if t.status == 'completed')
        return int((completed / len(tasks)) * 100)

    members = db.relationship('ProjectMember', back_populates='project', lazy=True)
    tasks = db.relationship('Task', backref='project', lazy=True)
    messages = db.relationship('Message', backref='project', lazy=True)
    folders = db.relationship('Folder', backref='project', lazy=True)
    files = db.relationship('File', backref='project', lazy=True)
    invitations = db.relationship('Invitation', backref='project', lazy=True)

class ProjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    role_in_project = db.Column(db.String(20), default='member')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='projects')
    project = db.relationship('Project', back_populates='members')

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

    files = db.relationship('File', backref='task', lazy=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)

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
    role = db.Column(db.String(20), default='member')
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)

# Создаем таблицы
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

# --- ДЕКОРАТОРЫ ---

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

def project_admin_or_manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        user = db.session.get(User, session['user_id'])
        project_id = kwargs.get('project_id')
        if not project_id:
            flash('Проект не найден.', 'danger')
            return redirect(url_for('dashboard'))
        
        member = ProjectMember.query.filter_by(user_id=user.id, project_id=project_id).first()
        if not member or member.role_in_project not in ['admin', 'manager']:
            flash('Доступ запрещен. Только для руководителей проекта.', 'danger')
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

# --- МАРШРУТЫ ---

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

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Пользователь с таким email уже существует.', 'danger')
            return redirect(url_for('register'))

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            company=company,
            email=email,
            password=password,
            role='user'
        )
        db.session.add(new_user)
        db.session.commit()

        if invitation and invitation.email == email:
            member = ProjectMember(
                user_id=new_user.id,
                project_id=invitation.project_id,
                role_in_project=invitation.role
            )
            db.session.add(member)
            invitation.is_used = True
            db.session.commit()
            flash(f'Вы зарегистрированы и добавлены в проект!', 'success')
        else:
            flash('Регистрация успешна! Теперь войдите в систему.', 'success')

        return redirect(url_for('login'))

    return render_template('register.html', invitation=invitation)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email, password=password).first()
        if user:
            session['user_id'] = user.id
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['user_role'] = user.role
            flash(f'Добро пожаловать, {user.first_name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Неверный email или пароль.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session['user_id'])
    
    my_projects = []
    for member in user.projects:
        my_projects.append(member.project)
    
    if user.role == 'admin':
        all_projects = Project.query.filter_by(is_active=True).all()
    else:
        all_projects = my_projects

    return render_template('dashboard.html', projects=all_projects, user=user)

# --- УПРАВЛЕНИЕ ПРОЕКТАМИ ---

@app.route('/project/create', methods=['GET', 'POST'])
@admin_required
def create_project():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        
        project = Project(
            name=name,
            description=description,
            created_by=session['user_id']
        )
        db.session.add(project)
        db.session.commit()
        
        member = ProjectMember(
            user_id=session['user_id'],
            project_id=project.id,
            role_in_project='admin'
        )
        db.session.add(member)
        db.session.commit()
        
        flash('Проект успешно создан!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('create_project.html')

@app.route('/project/<int:project_id>')
@login_required
def view_project(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа к этому проекту.', 'danger')
        return redirect(url_for('dashboard'))
    
    project = Project.query.get_or_404(project_id)
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(project_id)
    
    members = ProjectMember.query.filter_by(project_id=project.id).all()
    tasks = Task.query.filter_by(project_id=project.id, parent_task_id=None).all()
    messages = Message.query.filter_by(project_id=project.id).order_by(Message.created_at.asc()).all()
    
    folders = Folder.query.filter_by(project_id=project.id, parent_folder_id=None).all()
    files = File.query.filter_by(project_id=project.id, folder_id=None, task_id=None).all()
    
    all_users = User.query.filter(User.role != 'admin').all()
    
    # Получаем все проекты пользователя для виджета "Другие проекты"
    all_user_projects = []
    if user.role == 'admin':
        all_user_projects = Project.query.filter_by(is_active=True).all()
    else:
        for member in user.projects:
            all_user_projects.append(member.project)
    
    return render_template('project.html', 
                         project=project, 
                         members=members, 
                         tasks=tasks, 
                         messages=messages,
                         folders=folders,
                         files=files,
                         all_users=all_users,
                         all_user_projects=all_user_projects,
                         user=user,
                         user_role=user_role,
                         now=datetime.utcnow(),
                         projects=all_user_projects)  # Для бокового меню

@app.route('/project/<int:project_id>/settings')
@login_required
def project_settings(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(project_id)
    
    if user_role not in ['admin'] and user.role != 'admin':
        flash('Только руководитель проекта может управлять настройками.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))
    
    project = Project.query.get_or_404(project_id)
    members = ProjectMember.query.filter_by(project_id=project.id).all()
    
    # Получаем все проекты пользователя для бокового меню
    all_user_projects = []
    if user.role == 'admin':
        all_user_projects = Project.query.filter_by(is_active=True).all()
    else:
        for member in user.projects:
            all_user_projects.append(member.project)
    
    return render_template('project_settings.html', 
                         project=project, 
                         members=members,
                         user=user,
                         user_role=user_role,
                         projects=all_user_projects)  # Для бокового меню

# --- УПРАВЛЕНИЕ УЧАСТНИКАМИ ---

@app.route('/project/<int:project_id>/invite', methods=['POST'])
@project_admin_or_manager_required
def invite_user(project_id):
    email = request.form['email']
    role = request.form.get('role', 'member')
    
    existing_user = User.query.filter_by(email=email).first()
    
    if existing_user:
        existing_member = ProjectMember.query.filter_by(
            user_id=existing_user.id,
            project_id=project_id
        ).first()
        
        if existing_member:
            flash('Пользователь уже состоит в проекте.', 'warning')
            return redirect(url_for('project_settings', project_id=project_id))
        
        member = ProjectMember(
            user_id=existing_user.id,
            project_id=project_id,
            role_in_project=role
        )
        db.session.add(member)
        db.session.commit()
        flash(f'Пользователь {existing_user.first_name} добавлен в проект!', 'success')
    else:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow().replace(day=datetime.utcnow().day + 7)
        
        invitation = Invitation(
            email=email,
            project_id=project_id,
            invited_by=session['user_id'],
            role=role,
            token=token,
            expires_at=expires_at
        )
        db.session.add(invitation)
        db.session.commit()
        
        invite_link = url_for('register', token=token, _external=True)
        flash(f'Приглашение создано! Ссылка для регистрации: {invite_link}', 'success')
    
    return redirect(url_for('project_settings', project_id=project_id))

@app.route('/project/<int:project_id>/member/<int:member_id>/remove', methods=['POST'])
@project_admin_or_manager_required
def remove_member(project_id, member_id):
    member = ProjectMember.query.get_or_404(member_id)
    
    if member.user_id == Project.query.get(project_id).created_by:
        flash('Нельзя удалить создателя проекта.', 'danger')
        return redirect(url_for('project_settings', project_id=project_id))
    
    db.session.delete(member)
    db.session.commit()
    flash('Участник удален из проекта.', 'info')
    return redirect(url_for('project_settings', project_id=project_id))

@app.route('/project/<int:project_id>/member/<int:member_id>/change_role', methods=['POST'])
@project_admin_or_manager_required
def change_member_role(project_id, member_id):
    member = ProjectMember.query.get_or_404(member_id)
    new_role = request.form['role']
    
    if member.user_id == Project.query.get(project_id).created_by:
        flash('Нельзя изменить роль создателя проекта.', 'danger')
        return redirect(url_for('project_settings', project_id=project_id))
    
    member.role_in_project = new_role
    db.session.commit()
    flash('Роль участника изменена.', 'success')
    return redirect(url_for('project_settings', project_id=project_id))

# --- УПРАВЛЕНИЕ ПАПКАМИ ---

@app.route('/project/<int:project_id>/folder/create', methods=['POST'])
@login_required
def create_folder(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    name = request.form['name']
    parent_id = request.form.get('parent_id')
    if parent_id:
        parent_id = int(parent_id)
    else:
        parent_id = None
    
    existing = Folder.query.filter_by(
        project_id=project_id,
        parent_folder_id=parent_id,
        name=name
    ).first()
    
    if existing:
        flash('Папка с таким именем уже существует.', 'warning')
        return redirect(request.referrer or url_for('view_project', project_id=project_id))
    
    folder = Folder(
        name=name,
        project_id=project_id,
        parent_folder_id=parent_id,
        created_by=session['user_id']
    )
    db.session.add(folder)
    db.session.commit()
    
    flash(f'Папка "{name}" создана!', 'success')
    return redirect(request.referrer or url_for('view_project', project_id=project_id))

@app.route('/folder/<int:folder_id>')
@login_required
def view_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    
    if not check_project_access(folder.project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    subfolders = Folder.query.filter_by(parent_folder_id=folder_id).all()
    files = File.query.filter_by(folder_id=folder_id).all()
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(folder.project_id)
    
    # Получаем все проекты пользователя для бокового меню
    all_user_projects = []
    if user.role == 'admin':
        all_user_projects = Project.query.filter_by(is_active=True).all()
    else:
        for member in user.projects:
            all_user_projects.append(member.project)
    
    return render_template('folder.html', 
                         folder=folder, 
                         subfolders=subfolders, 
                         files=files,
                         user=user,
                         user_role=user_role,
                         projects=all_user_projects)  # Для бокового меню

@app.route('/folder/<int:folder_id>/delete', methods=['POST'])
@login_required
def delete_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    project_id = folder.project_id
    
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(project_id)
    
    if user_role not in ['admin', 'manager'] and folder.created_by != user.id:
        flash('У вас нет прав удалять эту папку.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))
    
    for file in folder.files:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.stored_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.session.delete(file)
    
    for subfolder in folder.subfolders:
        db.session.delete(subfolder)
    
    db.session.delete(folder)
    db.session.commit()
    
    flash('Папка удалена.', 'info')
    return redirect(url_for('view_project', project_id=project_id))

# --- УПРАВЛЕНИЕ ФАЙЛАМИ ---

@app.route('/project/<int:project_id>/upload', methods=['POST'])
@login_required
def upload_file(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    if 'file' not in request.files:
        flash('Файл не выбран.', 'warning')
        return redirect(request.referrer or url_for('view_project', project_id=project_id))
    
    file = request.files['file']
    if file.filename == '':
        flash('Файл не выбран.', 'warning')
        return redirect(request.referrer or url_for('view_project', project_id=project_id))
    
    folder_id = request.form.get('folder_id')
    task_id = request.form.get('task_id')
    
    if folder_id:
        folder_id = int(folder_id) if folder_id else None
    if task_id:
        task_id = int(task_id) if task_id else None
    
    original_name = file.filename
    ext = os.path.splitext(original_name)[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
    file.save(file_path)
    file_size = os.path.getsize(file_path)
    
    new_file = File(
        original_name=original_name,
        stored_name=stored_name,
        file_size=file_size,
        file_type=file.content_type,
        project_id=project_id,
        folder_id=folder_id,
        task_id=task_id,
        uploaded_by=session['user_id']
    )
    db.session.add(new_file)
    db.session.commit()
    
    flash(f'Файл "{original_name}" загружен!', 'success')
    
    if task_id:
        return redirect(url_for('view_task', task_id=task_id))
    elif folder_id:
        return redirect(url_for('view_folder', folder_id=folder_id))
    return redirect(url_for('view_project', project_id=project_id))

@app.route('/file/<int:file_id>/download')
@login_required
def download_file(file_id):
    file = File.query.get_or_404(file_id)
    
    if not check_project_access(file.project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        file.stored_name,
        download_name=file.original_name
    )

@app.route('/file/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(file_id):
    file = File.query.get_or_404(file_id)
    project_id = file.project_id
    
    user_role = get_user_role_in_project(project_id)
    if user_role not in ['admin', 'manager'] and file.uploaded_by != session['user_id']:
        flash('У вас нет прав удалять этот файл.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.stored_name)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    db.session.delete(file)
    db.session.commit()
    
    flash('Файл удален.', 'info')
    return redirect(request.referrer or url_for('view_project', project_id=project_id))

# --- УПРАВЛЕНИЕ ЗАДАЧАМИ ---

@app.route('/project/<int:project_id>/task/create', methods=['POST'])
@login_required
def create_task(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    title = request.form['title']
    description = request.form['description']
    assigned_to = request.form.get('assigned_to')
    due_date_str = request.form.get('due_date')
    parent_task_id = request.form.get('parent_task_id')
    
    due_date = None
    if due_date_str:
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
    
    task = Task(
        title=title,
        description=description,
        project_id=project_id,
        assigned_to=int(assigned_to) if assigned_to else None,
        due_date=due_date,
        created_by=session['user_id'],
        parent_task_id=int(parent_task_id) if parent_task_id else None
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
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    files = File.query.filter_by(task_id=task.id).all()
    subtasks = Task.query.filter_by(parent_task_id=task.id).all()
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(task.project_id)
    all_users = User.query.filter(User.role != 'admin').all()
    
    # Получаем все проекты пользователя для бокового меню
    all_user_projects = []
    if user.role == 'admin':
        all_user_projects = Project.query.filter_by(is_active=True).all()
    else:
        for member in user.projects:
            all_user_projects.append(member.project)
    
    return render_template('task_detail.html', 
                         task=task, 
                         files=files, 
                         subtasks=subtasks,
                         all_users=all_users,
                         user=user,
                         user_role=user_role,
                         now=datetime.utcnow(),
                         projects=all_user_projects)  # Для бокового меню

@app.route('/task/<int:task_id>/update_status', methods=['POST'])
@login_required
def update_task_status(task_id):
    task = Task.query.get_or_404(task_id)
    new_status = request.form['status']
    
    user = db.session.get(User, session['user_id'])
    user_role = get_user_role_in_project(task.project_id)
    
    if user_role not in ['admin', 'manager'] and task.assigned_to != user.id:
        flash('У вас нет прав менять статус этой задачи.', 'danger')
        return redirect(url_for('view_project', project_id=task.project_id))
    
    task.status = new_status
    db.session.commit()
    
    flash('Статус задачи обновлен!', 'success')
    return redirect(request.referrer or url_for('view_project', project_id=task.project_id))

@app.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    project_id = task.project_id
    
    user_role = get_user_role_in_project(project_id)
    if user_role not in ['admin', 'manager']:
        flash('У вас нет прав удалять задачи.', 'danger')
        return redirect(url_for('view_project', project_id=project_id))
    
    for subtask in task.subtasks:
        db.session.delete(subtask)
    
    db.session.delete(task)
    db.session.commit()
    flash('Задача удалена.', 'info')
    return redirect(url_for('view_project', project_id=project_id))

# --- ЧАТ ---

@app.route('/project/<int:project_id>/send_message', methods=['POST'])
@login_required
def send_message(project_id):
    if not check_project_access(project_id):
        flash('У вас нет доступа.', 'danger')
        return redirect(url_for('dashboard'))
    
    text = request.form['message']
    if text.strip():
        message = Message(
            text=text,
            user_id=session['user_id'],
            project_id=project_id
        )
        db.session.add(message)
        db.session.commit()
    
    return redirect(url_for('view_project', project_id=project_id))

# --- ЗАПУСК ---
if __name__ == '__main__':
    app.run(debug=True, port=5001)