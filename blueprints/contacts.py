from flask import Blueprint, request, redirect, url_for, flash, session

from extensions import db
from models import User, ContactPerson, Customer, Supplier
from decorators import login_required

bp = Blueprint('contacts', __name__)


@bp.route('/contact/create', methods=['POST'])
@login_required
def create_contact():
    """Создать контактное лицо у заказчика или поставщика."""
    owner_type = request.form.get('owner_type')  # 'customer' | 'supplier'
    owner_id = request.form.get('owner_id')

    if owner_type not in ('customer', 'supplier') or not owner_id:
        flash('Неверные параметры.', 'danger')
        return redirect(request.referrer or url_for('customers.customers_list'))

    if owner_type == 'customer':
        owner = Customer.query.get_or_404(int(owner_id))
        contact = ContactPerson(
            full_name=request.form['full_name'],
            position=request.form.get('position'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            customer_id=owner.id,
        )
    else:
        owner = Supplier.query.get_or_404(int(owner_id))
        contact = ContactPerson(
            full_name=request.form['full_name'],
            position=request.form.get('position'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            supplier_id=owner.id,
        )

    db.session.add(contact)
    db.session.commit()
    flash(f'Контактное лицо добавлено: {contact.full_name}', 'success')

    if owner_type == 'customer':
        return redirect(url_for('customers.view_customer', customer_id=owner.id))
    return redirect(url_for('suppliers.view_supplier', supplier_id=owner.id))


@bp.route('/contact/<int:contact_id>/edit', methods=['POST'])
@login_required
def edit_contact(contact_id):
    contact = ContactPerson.query.get_or_404(contact_id)
    contact.full_name = request.form['full_name']
    contact.position = request.form.get('position')
    contact.phone = request.form.get('phone')
    contact.email = request.form.get('email')
    db.session.commit()
    flash('Контакт обновлён.', 'success')
    return redirect(request.referrer or url_for('customers.customers_list'))


@bp.route('/contact/<int:contact_id>/delete', methods=['POST'])
@login_required
def delete_contact(contact_id):
    contact = ContactPerson.query.get_or_404(contact_id)
    owner_type = contact.belongs_to_type
    owner_id = contact.customer_id or contact.supplier_id
    db.session.delete(contact)
    db.session.commit()
    flash('Контакт удалён.', 'info')

    if owner_type == 'customer':
        return redirect(url_for('customers.view_customer', customer_id=owner_id))
    return redirect(url_for('suppliers.view_supplier', supplier_id=owner_id))