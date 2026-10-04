import secrets
from datetime import timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import User, Project, ProjectMember, Invitation
from decorators import login_required
from utils import (
    utcnow, check_project_access, can_manage_project,
    get_user_role_in_project, get_user_projects,
)

bp = Blueprint('team', __name__)


# ============================================================
#  НАСТРОЙКИ ПРОЕКТА (КОМАНДА)
# ============================================================

@bp.route('/project/<int:project_id>/settings')
@login_required
def project_settings(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    user = User.query.get(session['user_id'])
    user_role = get_user_role_in_project(project_id)

    if not can_manage_project(project_id):
        flash('Только руководитель может управлять настройками.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    project = Project.query.get_or_404(project_id)

    # Разделяем участников
    members_all = ProjectMember.query.filter_by(project_id=project.id).all()

    members = [m for m in members_all if m.is_own_team]
    am_stanko_members = [m for m in members_all if m.is_am_stanko]
    guests = [m for m in members_all if m.is_guest]

    # ← Email'ы уже добавленных — для фильтрации в автокомплите
    existing_emails = set()
    for m in members_all:
        if m.user and m.user.email:
            existing_emails.add(m.user.email.lower())

    # Активные приглашения
    invitations = Invitation.query\
        .filter_by(project_id=project.id, is_used=False)\
        .order_by(Invitation.created_at.desc()).all()

    active_invitations = [inv for inv in invitations if inv.expires_at > utcnow()]

    return render_template('project_settings.html',
                           project=project,
                           members=members,
                           am_stanko_members=am_stanko_members,
                           guests=guests,
                           existing_emails=existing_emails,   # ← НОВОЕ
                           invitations=active_invitations,
                           user=user,
                           user_role=user_role,
                           projects=get_user_projects(user))


# ============================================================
#  ПРИГЛАШЕНИЕ В ПРОЕКТ
# ============================================================

@bp.route('/project/<int:project_id>/invite', methods=['POST'])
@login_required
def invite_user(project_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    email = request.form['email'].strip().lower()
    role = request.form.get('role', 'member')

    allowed_roles = dict(ProjectMember.SELECTABLE_ROLES).keys()
    if role not in allowed_roles:
        role = 'member'

    if not email:
        flash('Укажите email.', 'warning')
        return redirect(url_for('team.project_settings', project_id=project_id))

    existing_user = User.query.filter_by(email=email).first()

    if existing_user:
        if ProjectMember.query.filter_by(user_id=existing_user.id, project_id=project_id).first():
            flash(f'{existing_user.first_name} {existing_user.last_name} уже в проекте.', 'warning')
            return redirect(url_for('team.project_settings', project_id=project_id))

        new_member = ProjectMember(
            user_id=existing_user.id,
            project_id=project_id,
            role_in_project=role,
        )
        # Если роль из набора АМ Станко — снимаем флаг guest
        if role in ProjectMember.AM_STANKO_ROLES:
            new_member.is_guest = False

        db.session.add(new_member)
        db.session.commit()
        flash(f'{existing_user.first_name} {existing_user.last_name} добавлен в проект.', 'success')
        return redirect(url_for('team.project_settings', project_id=project_id))

    # Пользователя нет — создаём приглашение
    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(days=7)

    db.session.add(Invitation(
        email=email,
        project_id=project_id,
        invited_by=session['user_id'],
        role=role,
        token=token,
        expires_at=expires_at,
    ))
    db.session.commit()

    link = url_for('auth.register', token=token, _external=True)
    flash(f'Приглашение создано для {email}. Ссылка (скопируйте и передайте): {link}', 'success')

    print(f"🔗 Ссылка-приглашение для {email}: {link}")
    print(f"   Проект: {project_id}, роль: {role}, до {expires_at.strftime('%d.%m.%Y %H:%M')}")

    return redirect(url_for('team.project_settings', project_id=project_id))


# ============================================================
#  ОТМЕНА ПРИГЛАШЕНИЯ
# ============================================================

@bp.route('/project/<int:project_id>/invite/<int:invitation_id>/cancel', methods=['POST'])
@login_required
def cancel_invitation(project_id, invitation_id):
    """Отменить активное приглашение."""
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    inv = Invitation.query.get_or_404(invitation_id)
    if inv.project_id != project_id:
        flash('Приглашение не относится к этому проекту.', 'danger')
        return redirect(url_for('team.project_settings', project_id=project_id))

    email = inv.email
    db.session.delete(inv)
    db.session.commit()
    flash(f'Приглашение для {email} отменено.', 'info')
    return redirect(url_for('team.project_settings', project_id=project_id))


# ============================================================
#  УДАЛЕНИЕ УЧАСТНИКА
# ============================================================

@bp.route('/project/<int:project_id>/member/<int:member_id>/remove', methods=['POST'])
@login_required
def remove_member(project_id, member_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    member = ProjectMember.query.get_or_404(member_id)
    project = Project.query.get(project_id)

    if member.user_id == project.created_by:
        flash('Нельзя удалить создателя проекта.', 'danger')
        return redirect(url_for('team.project_settings', project_id=project_id))

    user_name = f"{member.user.first_name} {member.user.last_name}"
    db.session.delete(member)
    db.session.commit()
    flash(f'{user_name} удалён из проекта.', 'info')
    return redirect(url_for('team.project_settings', project_id=project_id))


# ============================================================
#  СМЕНА РОЛИ УЧАСТНИКА
# ============================================================

@bp.route('/project/<int:project_id>/member/<int:member_id>/change_role', methods=['POST'])
@login_required
def change_member_role(project_id, member_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    member = ProjectMember.query.get_or_404(member_id)
    project = Project.query.get(project_id)

    if member.user_id == project.created_by:
        flash('Нельзя менять роль создателя.', 'danger')
        return redirect(url_for('team.project_settings', project_id=project_id))

    new_role = request.form.get('role', 'member')
    allowed_roles = dict(ProjectMember.SELECTABLE_ROLES).keys()

    if new_role not in allowed_roles:
        flash('Недопустимая роль.', 'danger')
        return redirect(url_for('team.project_settings', project_id=project_id))

    # Если переводим в роль из набора АМ Станко — снимаем is_guest
    if new_role in ProjectMember.AM_STANKO_ROLES:
        member.is_guest = False

    member.role_in_project = new_role
    db.session.commit()
    flash('Роль изменена.', 'success')
    return redirect(url_for('team.project_settings', project_id=project_id))