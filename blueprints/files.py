import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_from_directory, current_app
from werkzeug.utils import secure_filename

from extensions import db
from models import User, Folder, File
from decorators import login_required
from utils import (
    check_project_access, can_manage_project, get_user_role_in_project,
    get_user_projects, _validate_folder_in_project, _validate_task_in_project,
)

bp = Blueprint('files', __name__)


@bp.route('/project/<int:project_id>/folder/create', methods=['POST'])
@login_required
def create_folder(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    parent_id = request.form.get('parent_id') or None
    parent_id_int = None
    if parent_id:
        parent = _validate_folder_in_project(int(parent_id), project_id)
        if not parent:
            flash('Родительская папка не найдена.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))
        parent_id_int = parent.id

    db.session.add(Folder(
        name=request.form['name'], project_id=project_id,
        parent_folder_id=parent_id_int, created_by=session['user_id']
    ))
    db.session.commit()
    flash('Папка создана!', 'success')
    return redirect(request.referrer or url_for('projects.view_project', project_id=project_id))


@bp.route('/folder/<int:folder_id>')
@login_required
def view_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if not check_project_access(folder.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    user = User.query.get(session['user_id'])
    return render_template('folder.html',
                           folder=folder,
                           subfolders=Folder.query.filter_by(parent_folder_id=folder_id).all(),
                           files=File.query.filter_by(folder_id=folder_id).all(),
                           user=user,
                           user_role=get_user_role_in_project(folder.project_id),
                           projects=get_user_projects(user))


@bp.route('/folder/<int:folder_id>/delete', methods=['POST'])
@login_required
def delete_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    pid = folder.project_id
    if not can_manage_project(pid):
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid))

    for f in folder.files:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], f.stored_name)
        if os.path.exists(path):
            os.remove(path)
        db.session.delete(f)
    for sf in folder.subfolders:
        db.session.delete(sf)
    db.session.delete(folder)
    db.session.commit()
    flash('Папка удалена.', 'info')
    return redirect(url_for('projects.view_project', project_id=pid))


@bp.route('/project/<int:project_id>/upload', methods=['POST'])
@login_required
def upload_file(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    if 'file' not in request.files or request.files['file'].filename == '':
        flash('Файл не выбран.', 'warning')
        return redirect(request.referrer or url_for('projects.view_project', project_id=project_id))

    file = request.files['file']
    folder_id = request.form.get('folder_id') or None
    task_id = request.form.get('task_id') or None

    folder_id_int = None
    if folder_id:
        folder = _validate_folder_in_project(int(folder_id), project_id)
        if not folder:
            flash('Папка не найдена.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))
        folder_id_int = folder.id

    task_id_int = None
    if task_id:
        task = _validate_task_in_project(int(task_id), project_id)
        if not task:
            flash('Задача не найдена.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id))
        task_id_int = task.id

    original_name = secure_filename(file.filename) or 'file'
    ext = os.path.splitext(original_name)[1].lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)
    file.save(path)

    db.session.add(File(
        original_name=file.filename, stored_name=stored_name,
        file_size=os.path.getsize(path), file_type=file.content_type,
        project_id=project_id, folder_id=folder_id_int, task_id=task_id_int,
        uploaded_by=session['user_id']
    ))
    db.session.commit()
    flash(f'Файл "{file.filename}" загружен!', 'success')

    if task_id_int:
        return redirect(url_for('tasks.view_task', task_id=task_id_int))
    if folder_id_int:
        return redirect(url_for('files.view_folder', folder_id=folder_id_int))
    return redirect(url_for('projects.view_project', project_id=project_id))


@bp.route('/file/<int:file_id>/download')
@login_required
def download_file(file_id):
    f = File.query.get_or_404(file_id)
    if not check_project_access(f.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], f.stored_name, download_name=f.original_name)


@bp.route('/file/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(file_id):
    f = File.query.get_or_404(file_id)
    pid = f.project_id
    if not can_manage_project(pid) and f.uploaded_by != session['user_id']:
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid))

    path = os.path.join(current_app.config['UPLOAD_FOLDER'], f.stored_name)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(f)
    db.session.commit()
    return redirect(request.referrer or url_for('projects.view_project', project_id=pid))