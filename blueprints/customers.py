import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import User, Customer, Project, ContactPerson, Task
from decorators import login_required
from utils import get_user_projects, get_available_customers, is_privileged

bp = Blueprint('customers', __name__)


# ============================================================
#  ВАЛИДАЦИЯ
# ============================================================

def _validate_customer_form(form):
    """Валидация полей заказчика. Возвращает (data, errors).

    data — dict с очищенными полями.
    errors — list[str] — сообщения для flash.
    """
    data = {}
    errors = []

    # Название
    name = (form.get('name') or '').strip()
    if not name:
        errors.append('Наименование обязательно.')
    elif len(name) > 200:
        errors.append('Наименование слишком длинное (макс. 200 символов).')
    data['name'] = name

    # ИНН — 10 или 12 цифр, либо пусто
    inn = (form.get('inn') or '').strip()
    if inn and not re.fullmatch(r'\d{10}|\d{12}', inn):
        errors.append('ИНН должен содержать 10 или 12 цифр.')
    data['inn'] = inn or None

    # Контактное лицо — до 100
    contact_person = (form.get('contact_person') or '').strip()
    if len(contact_person) > 100:
        errors.append('Контактное лицо слишком длинное (макс. 100 символов).')
    data['contact_person'] = contact_person or None

    # Телефон — до 50, разрешены цифры, +, -, (), пробел, точка, буквы (доб.)
    phone = (form.get('phone') or '').strip()
    if phone:
        if len(phone) > 50:
            errors.append('Телефон слишком длинный (макс. 50 символов).')
        elif not re.fullmatch(r'[0-9+\-() .A-Za-zА-Яа-я]+', phone):
            errors.append(
                'Телефон содержит недопустимые символы. '
                'Разрешены: цифры, +, -, (), пробел, точка.'
            )
    data['phone'] = phone or None

    # Email — до 100, базовая проверка @
    email = (form.get('email') or '').strip()
    if email:
        if len(email) > 100:
            errors.append('Email слишком длинный (макс. 100 символов).')
        elif '@' not in email or '.' not in email.split('@')[-1]:
            errors.append('Email некорректный.')
    data['email'] = email or None

    # Адрес — до 300
    address = (form.get('address') or '').strip()
    if len(address) > 300:
        errors.append('Адрес слишком длинный (макс. 300 символов).')
    data['address'] = address or None

    return data, errors


# ============================================================
#  ХЕЛПЕР
# ============================================================

def _log(action, customer, details=None):
    """Безопасно пишет действие в журнал (не ломает основной флоу)."""
    try:
        from services.audit import log_action
        log_action(action,
                   target_type='customer',
                   target_id=customer.id if customer else None,
                   target_name=customer.name if customer else None,
                   details=details)
    except Exception as e:
        print(f'⚠️ Ошибка логирования {action}: {e}')


# ============================================================
#  СПИСОК ЗАКАЗЧИКОВ
# ============================================================

@bp.route('/customers')
@login_required
def customers_list():
    user = User.query.get(session['user_id'])
    return render_template('customers.html',
                           customers=get_available_customers(user),
                           user=user,
                           projects=get_user_projects(user))


# ============================================================
#  СОЗДАНИЕ ЗАКАЗЧИКА
# ============================================================

@bp.route('/customer/create', methods=['GET', 'POST'])
@login_required
def create_customer():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        # ← Валидация
        data, errors = _validate_customer_form(request.form)

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('create_customer.html',
                                   user=user,
                                   projects=get_user_projects(user),
                                   form_data=request.form)  # ← сохраняем введённое

        # ← Проверка на дубликат по имени (регистронезависимо)
        existing = Customer.query.filter(
            db.func.lower(Customer.name) == data['name'].lower()
        ).first()

        if existing:
            flash(f'Заказчик «{existing.name}» уже есть в базе. Измените название.', 'danger')
            return render_template('create_customer.html',
                                   user=user,
                                   projects=get_user_projects(user),
                                   form_data=request.form)  # ← сохраняем введённое

        customer = Customer(**data)
        db.session.add(customer)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'⚠️ Ошибка сохранения заказчика: {e}')
            flash('Не удалось сохранить заказчика. Проверьте данные и попробуйте ещё раз.', 'danger')
            return render_template('create_customer.html',
                                   user=user,
                                   projects=get_user_projects(user),
                                   form_data=request.form)

        # ← Логируем создание
        _log('create_customer', customer)

        flash('Заказчик добавлен!', 'success')

        next_url = request.form.get('next') or request.referrer or url_for('customers.customers_list')
        return redirect(next_url)

    return render_template('create_customer.html',
                           user=user,
                           projects=get_user_projects(user),
                           form_data=request.form)  # ← пустая форма (request.form = пусто на GET)


# ============================================================
#  РЕДАКТИРОВАНИЕ ЗАКАЗЧИКА
# ============================================================

@bp.route('/customer/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    user = User.query.get(session['user_id'])
    customer = Customer.query.get_or_404(customer_id)

    # ← Админ и супервизор могут редактировать любого заказчика
    if is_privileged(user):
        can_edit = True
    else:
        can_edit = False
        for member in user.projects:
            if member.project.customer_id == customer_id:
                can_edit = True
                break
        # «Свободный» заказчик (не привязан ни к одному проекту) — видят все
        if not Project.query.filter_by(customer_id=customer_id).first():
            can_edit = True

    if not can_edit:
        flash('У вас нет прав на редактирование этого заказчика.', 'danger')
        return redirect(url_for('customers.customers_list'))

    if request.method == 'POST':
        # ← Валидация
        data, errors = _validate_customer_form(request.form)

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('edit_customer.html',
                                   customer=customer,
                                   user=user,
                                   projects=get_user_projects(user),
                                   form_data=request.form)

        # ← Проверка на дубликат (исключая текущего)
        existing = Customer.query.filter(
            db.func.lower(Customer.name) == data['name'].lower(),
            Customer.id != customer.id,
        ).first()

        if existing:
            flash(f'Заказчик «{existing.name}» уже есть в базе. Измените название.', 'danger')
            return render_template('edit_customer.html',
                                   customer=customer,
                                   user=user,
                                   projects=get_user_projects(user),
                                   form_data=request.form)

        # Запоминаем старое имя для логов
        old_name = customer.name

        for key, value in data.items():
            setattr(customer, key, value)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'⚠️ Ошибка сохранения заказчика: {e}')
            flash('Не удалось сохранить заказчика. Проверьте данные и попробуйте ещё раз.', 'danger')
            return render_template('edit_customer.html',
                                   customer=customer,
                                   user=user,
                                   projects=get_user_projects(user),
                                   form_data=request.form)

        # ← Логируем изменение
        details = None
        if old_name != data['name']:
            details = f'Переименован: «{old_name}» → «{data["name"]}»'
        _log('edit_customer', customer, details=details)

        flash('Заказчик обновлён!', 'success')
        return redirect(url_for('customers.customers_list'))

    return render_template('edit_customer.html',
                           customer=customer,
                           user=user,
                           projects=get_user_projects(user),
                           form_data=request.form)  # ← пустая форма на GET


# ============================================================
#  ПРОСМОТР ЗАКАЗЧИКА
# ============================================================

@bp.route('/customer/<int:customer_id>')
@login_required
def view_customer(customer_id):
    user = User.query.get(session['user_id'])
    customer = Customer.query.get_or_404(customer_id)

    # ← Админ и супервизор видят всех
    if is_privileged(user):
        can_view = True
    else:
        can_view = False
        for member in user.projects:
            if member.project.customer_id == customer_id:
                can_view = True
                break
        if not Project.query.filter_by(customer_id=customer_id).first():
            can_view = True

    if not can_view:
        flash('Нет доступа.', 'danger')
        return redirect(url_for('customers.customers_list'))

    return render_template('customer_detail.html',
                           customer=customer,
                           user=user,
                           projects=get_user_projects(user))


# ============================================================
#  УДАЛЕНИЕ ЗАКАЗЧИКА
# ============================================================

@bp.route('/customer/<int:customer_id>/delete', methods=['POST'])
@login_required
def delete_customer(customer_id):
    """Удаление заказчика.

    Разрешено только если:
    - нет привязанных проектов;
    - ни один контакт не назначен на задачи.
    """
    user = User.query.get(session['user_id'])
    customer = Customer.query.get_or_404(customer_id)

    # ← Админ и супервизор могут удалять любого
    if is_privileged(user):
        can_delete = True
    else:
        can_delete = False
        for member in user.projects:
            if member.project.customer_id == customer_id:
                can_delete = True
                break
        if not Project.query.filter_by(customer_id=customer_id).first():
            can_delete = True

    if not can_delete:
        flash('Нет прав на удаление этого заказчика.', 'danger')
        return redirect(url_for('customers.customers_list'))

    # Проверка 1: есть ли проекты с этим заказчиком?
    projects_count = Project.query.filter_by(customer_id=customer_id).count()
    if projects_count > 0:
        flash(
            f'Нельзя удалить заказчика: к нему привязано проектов — {projects_count}. '
            f'Сначала отвяжите его в проектах.',
            'danger'
        )
        return redirect(url_for('customers.view_customer', customer_id=customer_id))

    # Проверка 2: есть ли контакты, назначенные на задачи?
    contact_user_ids = [
        c.user_id for c in customer.contacts if c.user_id
    ]
    if contact_user_ids:
        assigned_tasks = Task.query.filter(Task.assigned_to.in_(contact_user_ids)).count()
        if assigned_tasks > 0:
            flash(
                f'Нельзя удалить заказчика: его контакты назначены на {assigned_tasks} задач(и). '
                f'Сначала переназначьте задачи.',
                'danger'
            )
            return redirect(url_for('customers.view_customer', customer_id=customer_id))

    # ← Логируем удаление ДО физического удаления (пока есть id и name)
    name = customer.name
    _log('delete_customer', customer, details=f'Удалён заказчик «{name}»')

    try:
        db.session.delete(customer)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'⚠️ Ошибка удаления заказчика: {e}')
        flash('Не удалось удалить заказчика. Попробуйте ещё раз.', 'danger')
        return redirect(url_for('customers.view_customer', customer_id=customer_id))

    flash(f'Заказчик «{name}» удалён.', 'success')
    return redirect(url_for('customers.customers_list'))