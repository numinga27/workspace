from flask import Blueprint, request, redirect, url_for, flash, session

from extensions import db
from models import Report
from decorators import login_required
from utils import check_project_access, can_manage_project, _validate_milestone_in_project

bp = Blueprint('reports', __name__)


@bp.route('/project/<int:project_id>/report/create', methods=['POST'])
@login_required
def create_report(project_id):
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    milestone_id = request.form.get('milestone_id') or None
    delay = request.form.get('delay_days', '0')

    milestone_id_int = None
    if milestone_id:
        ms = _validate_milestone_in_project(int(milestone_id), project_id)
        if not ms:
            flash('Веха не найдена в этом проекте.', 'danger')
            return redirect(url_for('projects.view_project', project_id=project_id) + '#reports')
        milestone_id_int = ms.id

    report = Report(
        title=request.form['title'], content=request.form.get('content', ''),
        project_id=project_id, milestone_id=milestone_id_int,
        author_id=session['user_id'],
        reason=request.form.get('reason', 'on_track'),
        reason_detail=request.form.get('reason_detail', ''),
        delay_days=int(delay) if delay and delay.isdigit() else 0,
    )
    db.session.add(report)
    db.session.commit()
    flash('Отчёт создан!', 'success')
    return redirect(url_for('projects.view_project', project_id=project_id) + '#reports')


@bp.route('/report/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    r = Report.query.get_or_404(report_id)
    pid = r.project_id
    if not can_manage_project(pid) and r.author_id != session['user_id']:
        flash('Нет прав.', 'danger')
        return redirect(url_for('projects.view_project', project_id=pid))
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for('projects.view_project', project_id=pid) + '#reports')