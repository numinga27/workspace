from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import timedelta

from extensions import db
from models import User, Invitation, ProjectMember
from utils import utcnow

bp = Blueprint('auth', __name__)


@bp.route('/')
def index():
    return redirect(url_for('auth.login'))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    token = request.args.get('token')
    invitation = None
    if token:
        invitation = Invitation.query.filter_by(token=token, is_used=False).first()
        if not invitation or invitation.expires_at < utcnow():
            flash('Приглашение недействительно или истекло.', 'danger')
            return redirect(url_for('auth.login'))

    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        company = request.form['company']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует.', 'danger')
            return redirect(url_for('auth.register'))

        new_user = User(
            first_name=first_name, last_name=last_name,
            company=company, email=email, role='user'
        )
        new_user.set_password(password)
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

        return redirect(url_for('auth.login'))

    return render_template('register.html', invitation=invitation)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.password.startswith(('pbkdf2:', 'scrypt:', 'argon2')):
                user.set_password(password)
                db.session.commit()

            session['user_id'] = user.id
            session['user_name'] = f"{user.first_name} {user.last_name}"
            session['user_role'] = user.role
            flash(f'Добро пожаловать, {user.first_name}!', 'success')
            return redirect(url_for('dashboard.dashboard'))
        flash('Неверный email или пароль.', 'danger')
    return render_template('login.html')


@bp.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('auth.login'))