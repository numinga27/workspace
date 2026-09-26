from flask import Blueprint, render_template, session

from models import User, Project
from decorators import login_required
from utils import utcnow, check_project_access
from services.stats import (
    calculate_project_stats,
    calculate_task_stats,
    calculate_employee_stats,
)
from services.pdf import generate_pdf_response

bp = Blueprint('pdf', __name__)


@bp.route('/project/<int:project_id>/report/pdf')
@login_required
def project_report_pdf(project_id):
    from flask import redirect, url_for, flash
    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    project = Project.query.get_or_404(project_id)
    user = User.query.get(session['user_id'])
    stats = calculate_project_stats(project)

    html_content = render_template(
        'pdf/project_report.html',
        project=project,
        stats=stats,
        user=user,
        now=utcnow()
    )

    filename = f"project_{project.id}_report_{utcnow().strftime('%Y%m%d')}.pdf"
    return generate_pdf_response(html_content, filename)


@bp.route('/task/<int:task_id>/report/pdf')
@login_required
def task_report_pdf(task_id):
    from flask import redirect, url_for, flash
    from models import Task

    task = Task.query.get_or_404(task_id)
    if not check_project_access(task.project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    user = User.query.get(session['user_id'])
    stats = calculate_task_stats(task)

    html_content = render_template(
        'pdf/task_report.html',
        task=task,
        stats=stats,
        user=user,
        now=utcnow()
    )

    filename = f"task_{task.id}_report_{utcnow().strftime('%Y%m%d')}.pdf"
    return generate_pdf_response(html_content, filename)


@bp.route('/project/<int:project_id>/employee/<int:user_id>/pdf')
@login_required
def employee_report_pdf(project_id, user_id):
    from flask import redirect, url_for, flash
    from models import ProjectMember

    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    project = Project.query.get_or_404(project_id)
    employee = User.query.get(user_id)
    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    member = ProjectMember.query.filter_by(user_id=user_id, project_id=project_id).first()
    if not member:
        flash('Сотрудник не участвует в этом проекте.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    current_user = User.query.get(session['user_id'])
    stats = calculate_employee_stats(project, employee)

    html_content = render_template(
        'pdf/employee_report.html',
        project=project,
        employee=employee,
        member=member,
        stats=stats,
        user=current_user,
        now=utcnow()
    )

    filename = f"employee_{employee.last_name}_{employee.id}_report_{utcnow().strftime('%Y%m%d')}.pdf"
    return generate_pdf_response(html_content, filename)


@bp.route('/project/<int:project_id>/employee/<int:user_id>/report')
@login_required
def employee_report_view(project_id, user_id):
    from flask import redirect, url_for, flash
    from models import ProjectMember
    from utils import get_user_projects

    if not check_project_access(project_id):
        flash('Нет доступа.', 'danger')
        return redirect(url_for('dashboard.dashboard'))

    project = Project.query.get_or_404(project_id)
    employee = User.query.get(user_id)
    if not employee:
        flash('Сотрудник не найден.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    member = ProjectMember.query.filter_by(user_id=user_id, project_id=project_id).first()
    if not member:
        flash('Сотрудник не участвует в этом проекте.', 'danger')
        return redirect(url_for('projects.view_project', project_id=project_id))

    user = User.query.get(session['user_id'])
    stats = calculate_employee_stats(project, employee)

    return render_template(
        'employee_report.html',
        project=project,
        employee=employee,
        member=member,
        stats=stats,
        user=user,
        now=utcnow(),
        projects=get_user_projects(user)
    )