from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import User, Supplier, Project
from decorators import login_required
from utils import get_user_projects, get_available_suppliers

bp = Blueprint('suppliers', __name__)


# ============================================================
#  ХЕЛПЕРЫ
# ============================================================

def _can_view_supplier(user, supplier_id):
    """Проверяет, может ли пользователь видеть карточку поставщика/субподрядчика."""
    if user.role == 'admin':
        return True

    # Если у пользователя есть проект с этим поставщиком или субподрядчиком
    for member in user.projects:
        if member.project.supplier_id == supplier_id:
            return True
        if member.project.subcontractor_id == supplier_id:
            return True

    # Если поставщик ещё не привязан ни к одному проекту — видят все
    if not Project.query.filter(
        (Project.supplier_id == supplier_id) | (Project.subcontractor_id == supplier_id)
    ).first():
        return True

    return False


def _can_edit_supplier(user, supplier_id):
    """Проверяет, может ли пользователь редактировать поставщика/субподрядчика."""
    if user.role == 'admin':
        return True

    for member in user.projects:
        if member.project.supplier_id == supplier_id:
            return True
        if member.project.subcontractor_id == supplier_id:
            return True

    return False


def _get_suppliers_by_type(user, supplier_type):
    """Возвращает список поставщиков или субподрядчиков для пользователя."""
    all_available = get_available_suppliers(user)
    return [s for s in all_available if s.supplier_type == supplier_type]


# ============================================================
#  СПИСОК: ПОСТАВЩИКИ
# ============================================================

@bp.route('/suppliers')
@login_required
def suppliers_list():
    user = User.query.get(session['user_id'])
    suppliers = _get_suppliers_by_type(user, 'supplier')

    return render_template('suppliers.html',
                           suppliers=suppliers,
                           user=user,
                           page_type='supplier',
                           page_title='Поставщики',
                           page_icon='bi-truck',
                           page_color='warning',
                           create_url=url_for('suppliers.create_supplier'),
                           view_url_endpoint='suppliers.view_supplier',
                           edit_url_endpoint='suppliers.edit_supplier',
                           projects=get_user_projects(user))


# ============================================================
#  СПИСОК: СУБПОДРЯДЧИКИ
# ============================================================

@bp.route('/subcontractors')
@login_required
def subcontractors_list():
    user = User.query.get(session['user_id'])
    subcontractors = _get_suppliers_by_type(user, 'subcontractor')

    return render_template('suppliers.html',
                           suppliers=subcontractors,
                           user=user,
                           page_type='subcontractor',
                           page_title='Субподрядчики',
                           page_icon='bi-people-fill',
                           page_color='info',
                           create_url=url_for('suppliers.create_subcontractor'),
                           view_url_endpoint='suppliers.view_subcontractor',
                           edit_url_endpoint='suppliers.edit_subcontractor',
                           projects=get_user_projects(user))


# ============================================================
#  СОЗДАНИЕ: ПОСТАВЩИК
# ============================================================

@bp.route('/supplier/create', methods=['GET', 'POST'])
@login_required
def create_supplier():
    return _create_supplier_internal(supplier_type='supplier')


# ============================================================
#  СОЗДАНИЕ: СУБПОДРЯДЧИК
# ============================================================

@bp.route('/subcontractor/create', methods=['GET', 'POST'])
@login_required
def create_subcontractor():
    return _create_supplier_internal(supplier_type='subcontractor')


def _create_supplier_internal(supplier_type):
    """Общая логика создания поставщика/субподрядчика."""
    user = User.query.get(session['user_id'])
    is_sub = supplier_type == 'subcontractor'

    if request.method == 'POST':
        supplier = Supplier(
            name=request.form['name'],
            inn=request.form.get('inn'),
            contact_person=request.form.get('contact_person'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            supplier_type=supplier_type,
        )
        db.session.add(supplier)
        db.session.commit()

        label = 'Субподрядчик' if is_sub else 'Поставщик'
        flash(f'{label} добавлен!', 'success')

        # Куда возвращаемся
        next_url = request.form.get('next') or request.referrer
        if not next_url:
            next_url = url_for('suppliers.subcontractors_list') if is_sub else url_for('suppliers.suppliers_list')
        return redirect(next_url)

    return render_template('create_supplier.html',
                           user=user,
                           page_type=supplier_type,
                           page_title='Новый субподрядчик' if is_sub else 'Новый поставщик',
                           page_icon='bi-people-fill' if is_sub else 'bi-truck',
                           page_color='info' if is_sub else 'warning',
                           list_url=url_for('suppliers.subcontractors_list') if is_sub else url_for('suppliers.suppliers_list'),
                           projects=get_user_projects(user))


# ============================================================
#  ПРОСМОТР: ПОСТАВЩИК
# ============================================================

@bp.route('/supplier/<int:supplier_id>')
@login_required
def view_supplier(supplier_id):
    return _view_supplier_internal(supplier_id)


# ============================================================
#  ПРОСМОТР: СУБПОДРЯДЧИК
# ============================================================

@bp.route('/subcontractor/<int:supplier_id>')
@login_required
def view_subcontractor(supplier_id):
    return _view_supplier_internal(supplier_id)


def _view_supplier_internal(supplier_id):
    """Общая логика просмотра карточки поставщика/субподрядчика."""
    user = User.query.get(session['user_id'])
    supplier = Supplier.query.get_or_404(supplier_id)
    is_sub = supplier.is_subcontractor

    if not _can_view_supplier(user, supplier_id):
        flash('Нет доступа.', 'danger')
        if is_sub:
            return redirect(url_for('suppliers.subcontractors_list'))
        return redirect(url_for('suppliers.suppliers_list'))

    return render_template('supplier_detail.html',
                           supplier=supplier,
                           user=user,
                           is_subcontractor=is_sub,
                           page_title='Субподрядчик' if is_sub else 'Поставщик',
                           page_icon='bi-people-fill' if is_sub else 'bi-truck',
                           page_color='info' if is_sub else 'warning',
                           list_url=url_for('suppliers.subcontractors_list') if is_sub else url_for('suppliers.suppliers_list'),
                           edit_url=url_for('suppliers.edit_subcontractor', supplier_id=supplier.id) if is_sub
                                     else url_for('suppliers.edit_supplier', supplier_id=supplier.id),
                           projects=get_user_projects(user))


# ============================================================
#  РЕДАКТИРОВАНИЕ: ПОСТАВЩИК
# ============================================================

@bp.route('/supplier/<int:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_supplier(supplier_id):
    return _edit_supplier_internal(supplier_id)


# ============================================================
#  РЕДАКТИРОВАНИЕ: СУБПОДРЯДЧИК
# ============================================================

@bp.route('/subcontractor/<int:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_subcontractor(supplier_id):
    return _edit_supplier_internal(supplier_id)


def _edit_supplier_internal(supplier_id):
    """Общая логика редактирования поставщика/субподрядчика."""
    user = User.query.get(session['user_id'])
    supplier = Supplier.query.get_or_404(supplier_id)
    is_sub = supplier.is_subcontractor

    if not _can_edit_supplier(user, supplier_id):
        flash('Нет прав на редактирование.', 'danger')
        if is_sub:
            return redirect(url_for('suppliers.subcontractors_list'))
        return redirect(url_for('suppliers.suppliers_list'))

    if request.method == 'POST':
        supplier.name = request.form['name']
        supplier.inn = request.form.get('inn')
        supplier.contact_person = request.form.get('contact_person')
        supplier.phone = request.form.get('phone')
        supplier.email = request.form.get('email')
        supplier.address = request.form.get('address')
        db.session.commit()

        label = 'Субподрядчик' if is_sub else 'Поставщик'
        flash(f'{label} обновлён!', 'success')

        if is_sub:
            return redirect(url_for('suppliers.view_subcontractor', supplier_id=supplier.id))
        return redirect(url_for('suppliers.view_supplier', supplier_id=supplier.id))

    return render_template('edit_supplier.html',
                           supplier=supplier,
                           user=user,
                           is_subcontractor=is_sub,
                           page_title='Редактирование субподрядчика' if is_sub else 'Редактирование поставщика',
                           page_icon='bi-people-fill' if is_sub else 'bi-truck',
                           page_color='info' if is_sub else 'warning',
                           view_url=url_for('suppliers.view_subcontractor', supplier_id=supplier.id) if is_sub
                                    else url_for('suppliers.view_supplier', supplier_id=supplier.id),
                           projects=get_user_projects(user))