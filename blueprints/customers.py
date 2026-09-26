from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from extensions import db
from models import User, Customer, Project
from decorators import login_required
from utils import get_user_projects, get_available_customers

bp = Blueprint('customers', __name__)


@bp.route('/customers')
@login_required
def customers_list():
    user = User.query.get(session['user_id'])
    return render_template('customers.html',
                           customers=get_available_customers(user),
                           user=user,
                           projects=get_user_projects(user))


@bp.route('/customer/create', methods=['GET', 'POST'])
@login_required
def create_customer():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        customer = Customer(
            name=request.form['name'],
            inn=request.form.get('inn'),
            contact_person=request.form.get('contact_person'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
        )
        db.session.add(customer)
        db.session.commit()
        flash('Заказчик добавлен!', 'success')

        next_url = request.form.get('next') or request.referrer or url_for('customers.customers_list')
        return redirect(next_url)

    return render_template('create_customer.html',
                           user=user,
                           projects=get_user_projects(user))


@bp.route('/customer/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    user = User.query.get(session['user_id'])
    customer = Customer.query.get_or_404(customer_id)

    can_edit = False
    if user.role == 'admin':
        can_edit = True
    else:
        for member in user.projects:
            if member.project.customer_id == customer_id:
                can_edit = True
                break
        if not Project.query.filter_by(customer_id=customer_id).first():
            can_edit = True

    if not can_edit:
        flash('У вас нет прав на редактирование этого заказчика.', 'danger')
        return redirect(url_for('customers.customers_list'))

    if request.method == 'POST':
        customer.name = request.form['name']
        customer.inn = request.form.get('inn')
        customer.contact_person = request.form.get('contact_person')
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        customer.address = request.form.get('address')
        db.session.commit()
        flash('Заказчик обновлён!', 'success')
        return redirect(url_for('customers.customers_list'))

    return render_template('edit_customer.html',
                           customer=customer,
                           user=user,
                           projects=get_user_projects(user))



@bp.route('/customer/<int:customer_id>')
@login_required
def view_customer(customer_id):
    user = User.query.get(session['user_id'])
    customer = Customer.query.get_or_404(customer_id)

    can_view = user.role == 'admin'
    if not can_view:
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