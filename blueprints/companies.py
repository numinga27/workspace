from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from sqlalchemy import or_

from extensions import db
from models import User, Company, Project
from decorators import login_required, privileged_required
from utils import get_user_projects, is_privileged

bp = Blueprint('companies', __name__, url_prefix='/companies')


# ============================================================
#  СПИСОК ФИЛИАЛОВ
# ============================================================

@bp.route('/')
@login_required
def companies_list():
    """Список всех филиалов. Видят все, управляют — админ/супервизор."""
    user = User.query.get(session['user_id'])

    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    sort = request.args.get('sort', 'name')

    query = Company.query

    if q:
        like = f'%{q}%'
        query = query.filter(
            or_(
                Company.name.ilike(like),
                Company.inn.ilike(like),
                Company.email.ilike(like),
                Company.address.ilike(like),
            )
        )

    if status_filter == 'active':
        query = query.filter(Company.is_active.is_(True))
    elif status_filter == 'inactive':
        query = query.filter(Company.is_active.is_(False))

    if sort == 'newest':
        query = query.order_by(Company.created_at.desc())
    else:
        query = query.order_by(Company.name.asc())

    companies = query.all()

    stats = {
        'total': Company.query.count(),
        'active': Company.query.filter_by(is_active=True).count(),
        'inactive': Company.query.filter_by(is_active=False).count(),
    }

    return render_template('companies/list.html',
                           user=user,
                           companies=companies,
                           stats=stats,
                           q=q,
                           status_filter=status_filter,
                           sort=sort,
                           can_manage=is_privileged(user),
                           projects=get_user_projects(user))


# ============================================================
#  СОЗДАНИЕ
# ============================================================

@bp.route('/create', methods=['GET', 'POST'])
@login_required
@privileged_required
def companies_create():
    """Создать филиал. Только админ/супервизор."""
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        name = request.form.get('name', '').strip()

        errors = []
        if not name:
            errors.append('Название обязательно.')
        if name and Company.query.filter_by(name=name).first():
            errors.append(f'Филиал «{name}» уже существует.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('companies/form.html',
                                   user=user,
                                   edit_company=None,
                                   form_data=request.form,
                                   projects=get_user_projects(user))

        company = Company(
            name=name[:200],
            inn=(request.form.get('inn') or '').strip()[:20] or None,
            address=(request.form.get('address') or '').strip()[:300] or None,
            phone=(request.form.get('phone') or '').strip()[:30] or None,
            email=(request.form.get('email') or '').strip()[:100] or None,
            color=request.form.get('color', '#6366f1'),
            is_active=True,
            created_by_id=user.id,
        )
        db.session.add(company)
        db.session.commit()

        flash(f'Филиал «{company.name}» создан.', 'success')
        return redirect(url_for('companies.companies_list'))

    return render_template('companies/form.html',
                           user=user,
                           edit_company=None,
                           form_data={},
                           projects=get_user_projects(user))


# ============================================================
#  РЕДАКТИРОВАНИЕ
# ============================================================

@bp.route('/<int:company_id>/edit', methods=['GET', 'POST'])
@login_required
@privileged_required
def companies_edit(company_id):
    """Редактировать филиал."""
    user = User.query.get(session['user_id'])
    company = Company.query.get_or_404(company_id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()

        errors = []
        if not name:
            errors.append('Название обязательно.')
        if name:
            existing = Company.query.filter_by(name=name).first()
            if existing and existing.id != company.id:
                errors.append(f'Филиал «{name}» уже существует.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('companies/form.html',
                                   user=user,
                                   edit_company=company,
                                   form_data=request.form,
                                   projects=get_user_projects(user))

        company.name = name[:200]
        company.inn = (request.form.get('inn') or '').strip()[:20] or None
        company.address = (request.form.get('address') or '').strip()[:300] or None
        company.phone = (request.form.get('phone') or '').strip()[:30] or None
        company.email = (request.form.get('email') or '').strip()[:100] or None
        company.color = request.form.get('color', company.color)

        db.session.commit()
        flash(f'Филиал «{company.name}» обновлён.', 'success')
        return redirect(url_for('companies.companies_list'))

    return render_template('companies/form.html',
                           user=user,
                           edit_company=company,
                           form_data={},
                           projects=get_user_projects(user))


# ============================================================
#  АКТИВАЦИЯ / ДЕАКТИВАЦИЯ
# ============================================================

@bp.route('/<int:company_id>/toggle-active', methods=['POST'])
@login_required
@privileged_required
def companies_toggle_active(company_id):
    """Активировать или деактивировать филиал."""
    company = Company.query.get_or_404(company_id)
    company.is_active = not company.is_active
    db.session.commit()

    if company.is_active:
        flash(f'Филиал «{company.name}» активирован.', 'success')
    else:
        flash(f'Филиал «{company.name}» деактивирован. '
              f'В новых проектах его не будет в списке.', 'info')

    return redirect(url_for('companies.companies_list'))


# ============================================================
#  УДАЛЕНИЕ
# ============================================================

@bp.route('/<int:company_id>/delete', methods=['POST'])
@login_required
@privileged_required
def companies_delete(company_id):
    """Удалить филиал, если к нему не привязаны проекты."""
    company = Company.query.get_or_404(company_id)

    projects_count = Project.query.filter_by(company_id=company.id).count()
    if projects_count > 0:
        flash(f'Нельзя удалить филиал «{company.name}»: '
              f'к нему привязано проектов — {projects_count}. '
              f'Сначала отвяжите или деактивируйте.',
              'danger')
        return redirect(url_for('companies.companies_list'))

    name = company.name
    db.session.delete(company)
    db.session.commit()
    flash(f'Филиал «{name}» удалён.', 'success')
    return redirect(url_for('companies.companies_list'))