from flask import Blueprint, redirect, url_for, flash, session, jsonify, request

from extensions import db
from models import Message
from decorators import login_required
from utils import check_project_access, mark_project_as_read

bp = Blueprint('chat', __name__)


@bp.route('/project/<int:project_id>/send_message', methods=['POST'])
@login_required
def send_message(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    text = request.form['message']
    if text.strip():
        db.session.add(Message(text=text, user_id=session['user_id'], project_id=project_id))
        db.session.commit()
        mark_project_as_read(session['user_id'], project_id)
    return redirect(url_for('projects.view_project', project_id=project_id) + '#chat')


@bp.route('/project/<int:project_id>/mark_read', methods=['POST'])
@login_required
def mark_read(project_id):
    if not check_project_access(project_id):
        return jsonify({'success': False}), 403
    mark_project_as_read(session['user_id'], project_id)
    return jsonify({'success': True})