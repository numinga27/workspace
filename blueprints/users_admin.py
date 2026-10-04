from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy import or_

from extensions import db
from models import User, Project, Task, ProjectMember
from decorators import login_required, privileged_required, admin_required
from utils import get_user_projects

bp = Blueprint('users_admin', __name__, url_prefix='/admin')


# ============================================================
#  СПИСОК ПОЛЬЗОВАТЕЛЕЙ
# ============================================================

@bp.route('/users')
@login_required
@privileged_required
def users_list():
    """Список всех пользователей с фильтрами и поиском."""
    current_user = User.query.get(session['user_id'])

    q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '')
    status_filter = request.args.get('status', '')
    sort = request.args.get('sort', 'newest')

    query = User.query

    if q:
        like = f'%{q}%'
        query = query.filter(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.company.ilike(like),
            )
        )

    if role_filter in ('admin', 'supervisor', 'user'):
        query = query.filter(User.role == role_filter)

    if status_filter == 'active':
        query = query.filter(User.is_active.is_(True))
    elif status_filter == 'inactive':
        query = query.filter(User.is_active.is_(False))

    if sort == 'oldest':
        query = query.order_by(User.created_at.asc())
    elif sort == 'name':
        query = query.order_by(User.last_name.asc(), User.first_name.asc())
    elif sort == 'email':
        query = query.order_by(User.email.asc())
    else:
        query = query.order_by(User.created_at.desc())

    users = query.all()

    stats = {
        'total': User.query.count(),
        'admins': User.query.filter_by(role='admin').count(),
        'supervisors': User.query.filter_by(role='supervisor').count(),
        'regular': User.query.filter_by(role='user').count(),
        'inactive': User.query.filter_by(is_active=False).count(),
    }

    return render_template('admin/users.html',
                           user=current_user,
                           users=users,
                           stats=stats,
                           q=q,
                           role_filter=role_filter,
                           status_filter=status_filter,
                           sort=sort,
                           projects=get_user_projects(current_user))


# ============================================================
#  СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@privileged_required
def users_create():
    """Создать нового пользователя."""
    current_user = User.query.get(session['user_id'])

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        company = request.form.get('company', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        role = request.form.get('role', 'user')

        errors = []

        if not first_name:
            errors.append('Имя обязательно.')
        if not last_name:
            errors.append('Фамилия обязательна.')
        if not company:
            errors.append('Компания обязательна.')
        if not email:
            errors.append('Email обязателен.')
        if not password:
            errors.append('Пароль обязателен.')
        if len(password) < 6:
            errors.append('Пароль должен быть не короче 6 символов.')
        if password != password_confirm:
            errors.append('Пароли не совпадают.')
        if role not in ('user', 'supervisor', 'admin'):
            errors.append('Недопустимая роль.')

        if role == 'admin' and not current_user.is_admin:
            errors.append('Только главный администратор может назначать роль "Администратор".')

        if email and User.query.filter_by(email=email).first():
            errors.append(f'Пользователь с email {email} уже существует.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/user_form.html',
                                   user=current_user,
                                   edit_user=None,
                                   form_data=request.form,
                                   projects=get_user_projects(current_user))

        new_user = User(
            first_name=first_name[:50],
            last_name=last_name[:50],
            company=company[:100],
            email=email[:100],
            role=role,
            is_active=True,
            created_by_id=current_user.id,
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash(f'Пользователь {new_user.full_name} создан '
              f'(роль: {new_user.role_display}).', 'success')
        return redirect(url_for('users_admin.users_list'))

    return render_template('admin/user_form.html',
                           user=current_user,
                           edit_user=None,
                           form_data={},
                           projects=get_user_projects(current_user))


# ============================================================
#  РЕДАКТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@privileged_required
def users_edit(user_id):
    """Редактировать пользователя (имя, компания, email, пароль)."""
    current_user = User.query.get(session['user_id'])
    edit_user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        company = request.form.get('company', '').strip()
        email = request.form.get('email', '').strip().lower()
        new_password = request.form.get('new_password', '').strip()

        errors = []

        if not first_name:
            errors.append('Имя обязательно.')
        if not last_name:
            errors.append('Фамилия обязательна.')
        if not company:
            errors.append('Компания обязательна.')
        if not email:
            errors.append('Email обязателен.')

        if email:
            existing = User.query.filter_by(email=email).first()
            if existing and existing.id != edit_user.id:
                errors.append(f'Email {email} уже занят другим пользователем.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/user_form.html',
                                   user=current_user,
                                   edit_user=edit_user,
                                   form_data=request.form,
                                   projects=get_user_projects(current_user))

        edit_user.first_name = first_name[:50]
        edit_user.last_name = last_name[:50]
        edit_user.company = company[:100]
        edit_user.email = email[:100]

        if new_password:
            if len(new_password) < 6:
                flash('Новый пароль должен быть не короче 6 символов.', 'danger')
                return render_template('admin/user_form.html',
                                       user=current_user,
                                       edit_user=edit_user,
                                       form_data=request.form,
                                       projects=get_user_projects(current_user))
            edit_user.set_password(new_password)
            flash('Пароль обновлён.', 'success')

        db.session.commit()
        flash(f'Данные {edit_user.full_name} обновлены.', 'success')
        return redirect(url_for('users_admin.users_list'))

    return render_template('admin/user_form.html',
                           user=current_user,
                           edit_user=edit_user,
                           form_data={},
                           projects=get_user_projects(current_user))


# ============================================================
#  СМЕНА РОЛИ
# ============================================================

@bp.route('/users/<int:user_id>/set-role', methods=['POST'])
@login_required
@privileged_required
def users_set_role(user_id):
    """Сменить роль пользователя: user / supervisor / admin."""
    current_user = User.query.get(session['user_id'])
    target = User.query.get_or_404(user_id)

    new_role = request.form.get('role', '').strip()

    if new_role not in ('user', 'supervisor', 'admin'):
        flash('Недопустимая роль.', 'danger')
        return redirect(url_for('users_admin.users_list'))

    if target.id == current_user.id:
        flash('Нельзя изменить свою собственную роль.', 'warning')
        return redirect(url_for('users_admin.users_list'))

    if new_role == 'admin' and not current_user.is_admin:
        flash('Только главный администратор может назначать администраторов.', 'danger')
        return redirect(url_for('users_admin.users_list'))

    if target.role == 'admin' and not current_user.is_admin:
        flash('Только главный администратор может изменять роль администратора.', 'danger')
        return redirect(url_for('users_admin.users_list'))

    if target.role == 'admin' and new_role != 'admin':
        admins_count = User.query.filter_by(role='admin', is_active=True).count()
        if admins_count <= 1:
            flash('Нельзя понизить последнего администратора системы.', 'danger')
            return redirect(url_for('users_admin.users_list'))

    old_role = target.role
    target.role = new_role
    db.session.commit()

    flash(f'Роль {target.full_name} изменена: '
          f'{_role_display(old_role)} → {_role_display(new_role)}.', 'success')
    return redirect(url_for('users_admin.users_list'))


def _role_display(role):
    return {
        'admin': 'Администратор',
        'supervisor': 'Супервизор',
        'user': 'Пользователь',
    }.get(role, role)


# ============================================================
#  БЛОКИРОВКА / РАЗБЛОКИРОВКА
# ============================================================

@bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@privileged_required
def users_toggle_active(user_id):
    """Активировать / деактивировать пользователя."""
    current_user = User.query.get(session['user_id'])
    target = User.query.get_or_404(user_id)

    if target.id == current_user.id:
        flash('Нельзя заблокировать самого себя.', 'warning')
        return redirect(url_for('users_admin.users_list'))

    if target.role == 'admin' and not current_user.is_admin:
        flash('Только главный администратор может блокировать администраторов.', 'danger')
        return redirect(url_for('users_admin.users_list'))

    target.is_active = not target.is_active
    db.session.commit()

    if target.is_active:
        flash(f'{target.full_name} разблокирован.', 'success')
    else:
        flash(f'{target.full_name} заблокирован.', 'warning')

    return redirect(url_for('users_admin.users_list'))


# ============================================================
#  УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@privileged_required
def users_delete(user_id):
    """Удалить пользователя, если у него нет активных связей."""
    current_user = User.query.get(session['user_id'])
    target = User.query.get_or_404(user_id)

    if target.id == current_user.id:
        flash('Нельзя удалить самого себя.', 'danger')
        return redirect(url_for('users_admin.users_list'))

    if target.role == 'admin' and not current_user.is_admin:
        flash('Только главный администратор может удалять администраторов.', 'danger')
        return redirect(url_for('users_admin.users_list'))

    if target.role == 'admin':
        admins_count = User.query.filter_by(role='admin', is_active=True).count()
        if admins_count <= 1:
            flash('Нельзя удалить последнего администратора системы.', 'danger')
            return redirect(url_for('users_admin.users_list'))

    created_projects = Project.query.filter_by(created_by=target.id).count()
    if created_projects > 0:
        flash(f'Нельзя удалить: {target.full_name} создал {created_projects} проект(ов). '
              f'Сначала передайте проекты другому пользователю или удалите их.',
              'danger')
        return redirect(url_for('users_admin.users_list'))

    assigned_tasks = Task.query.filter_by(assigned_to=target.id).count()
    if assigned_tasks > 0:
        flash(f'Нельзя удалить: на {target.full_name} назначено {assigned_tasks} задач(и). '
              f'Сначала переназначьте задачи.',
              'danger')
        return redirect(url_for('users_admin.users_list'))

    created_tasks = Task.query.filter_by(created_by=target.id).count()
    if created_tasks > 0:
        flash(f'Нельзя удалить: {target.full_name} создал {created_tasks} задач(и).',
              'danger')
        return redirect(url_for('users_admin.users_list'))

    name = target.full_name
    ProjectMember.query.filter_by(user_id=target.id).delete()
    db.session.delete(target)
    db.session.commit()

    flash(f'Пользователь {name} удалён.', 'success')
    return redirect(url_for('users_admin.users_list'))


# ============================================================
#  API: ПОИСК ПОЛЬЗОВАТЕЛЕЙ (для автокомплита)
# ============================================================

@bp.route('/api/users/search')
@login_required
@privileged_required
def api_users_search():
    """Поиск зарегистрированных пользователей для автокомплита.

    GET-параметры:
      q     — строка поиска. Если пусто — возвращаются первые N пользователей.
      limit — сколько вернуть (по умолчанию 20, максимум 50).

    Возвращает JSON-массив объектов:
      {id, email, name, company, role_display}
    """
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20) or 20), 50)

    query = User.query.filter(User.is_active.is_(True))

    if q:
        like = f'%{q}%'
        query = query.filter(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.company.ilike(like),
            )
        )

    users = query.order_by(
        User.last_name.asc(),
        User.first_name.asc()
    ).limit(limit).all()

    return jsonify([{
        'id': u.id,
        'email': u.email,
        'name': u.full_name,
        'company': u.company or '',
        'role_display': u.role_display,
    } for u in users])