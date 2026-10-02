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
    members = ProjectMember.query.filter_by(project_id=project.id).all()

    # ← НОВОЕ: активные приглашения по проекту
    invitations = Invitation.query\
        .filter_by(project_id=project.id, is_used=False)\
        .order_by(Invitation.created_at.desc()).all()

    # Только те, у которых срок не истёк
    active_invitations = [inv for inv in invitations if inv.expires_at > utcnow()]

    return render_template('project_settings.html',
                           project=project,
                           members=members,
                           invitations=active_invitations,   # ← НОВОЕ
                           user=user,
                           user_role=user_role,
                           projects=get_user_projects(user))


@bp.route('/project/<int:project_id>/invite', methods=['POST'])
@login_required
def invite_user(project_id):
    if not can_manage_project(project_id):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    email = request.form['email'].strip().lower()
    role = request.form.get('role', 'member')

    if not email:
        flash('Укажите email.', 'warning')
        return redirect(url_for('team.project_settings', project_id=project_id))

    existing_user = User.query.filter_by(email=email).first()

    if existing_user:
        # Пользователь уже зарегистрирован — сразу добавляем в проект
        if ProjectMember.query.filter_by(user_id=existing_user.id, project_id=project_id).first():
            flash(f'{existing_user.first_name} {existing_user.last_name} уже в проекте.', 'warning')
            return redirect(url_for('team.project_settings', project_id=project_id))

        db.session.add(ProjectMember(
            user_id=existing_user.id,
            project_id=project_id,
            role_in_project=role,
        ))
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

    # ← НОВОЕ: показываем ссылку прямо в UI (flash)
    flash(f'Приглашение создано для {email}. Ссылка (скопируйте и передайте): {link}', 'success')

    # Дублируем в логи — на всякий случай
    print(f"🔗 Ссылка-приглашение для {email}: {link}")
    print(f"   Проект: {project_id}, роль: {role}, действует до {expires_at.strftime('%d.%m.%Y %H:%M')}")

    return redirect(url_for('team.project_settings', project_id=project_id))


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

    db.session.delete(member)
    db.session.commit()
    flash('Участник удалён.', 'info')
    return redirect(url_for('team.project_settings', project_id=project_id))


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

    member.role_in_project = request.form['role']
    db.session.commit()
    flash('Роль изменена.', 'success')
    return redirect(url_for('team.project_settings', project_id=project_id))