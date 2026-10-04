from flask import Flask
from datetime import datetime, timezone
import click

from config import Config
from extensions import db, mail, FLASK_MAIL_AVAILABLE
from models import User
from blueprints import register_blueprints


# ============================================================
#  ХЕЛПЕРЫ ДЛЯ CONTEXT PROCESSORS
# ============================================================

def _utcnow():
    return datetime.now(timezone.utc)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- Инициализация расширений ---
    db.init_app(app)
    if FLASK_MAIL_AVAILABLE and mail is not None:
        mail.init_app(app)

    # --- Регистрация Blueprints ---
    register_blueprints(app)

    # ============================================================
    #  CONTEXT PROCESSORS
    # ============================================================

    @app.context_processor
    def inject_unread_counts():
        """Непрочитанные сообщения в чатах проектов."""
        from flask import session
        from utils import get_unread_counts
        if 'user_id' in session:
            try:
                user = User.query.get(session['user_id'])
                if user:
                    return {'unread_counts': get_unread_counts(user)}
            except Exception as e:
                print(f'⚠️ Ошибка get_unread_counts: {e}')
        return {'unread_counts': {}}

    @app.context_processor
    def inject_overdue_count():
        """Просроченные задачи текущего пользователя."""
        from flask import session
        from models import Task
        if 'user_id' in session:
            try:
                user = User.query.get(session['user_id'])
                if user:
                    overdue_count = Task.query.filter_by(assigned_to=user.id)\
                        .filter(Task.status != 'completed')\
                        .filter(Task.due_date < _utcnow()).count()
                    return {'my_overdue_count': overdue_count}
            except Exception as e:
                print(f'⚠️ Ошибка подсчёта просроченных: {e}')
        return {'my_overdue_count': 0}

    @app.context_processor
    def inject_unread_tasks_count():
        """Количество непрочитанных задач, назначенных текущему пользователю."""
        from flask import session
        from utils import get_unread_tasks_count
        if 'user_id' in session:
            try:
                count = get_unread_tasks_count(session['user_id'])
                return {'unread_tasks_count': count}
            except Exception as e:
                print(f'⚠️ Ошибка get_unread_tasks_count: {e}')
        return {'unread_tasks_count': 0}
    @app.context_processor
    def inject_unread_mentions():
        """Непрочитанные упоминания (@) пользователя — общий счётчик и по проектам."""
        from flask import session
        from utils import get_unread_mentions_count, get_unread_mentions_by_project
        if 'user_id' in session:
            try:
                return {
                    'unread_mentions_count': get_unread_mentions_count(session['user_id']),
                    'unread_mentions_by_project': get_unread_mentions_by_project(session['user_id']),
                }
            except Exception as e:
                print(f'⚠️ Ошибка get_unread_mentions: {e}')
        return {
            'unread_mentions_count': 0,
            'unread_mentions_by_project': {},
        }
    # ============================================================
    #  СОЗДАНИЕ ТАБЛИЦ И SEED ГЛАВНОГО АДМИНА
    # ============================================================

    with app.app_context():
        db.create_all()

        # ← Автомиграция старых ролей (на случай, если в БД осталось 'am_stanko')
        from models import ProjectMember
        old_rows = ProjectMember.query.filter_by(role_in_project='am_stanko').all()
        if old_rows:
            for m in old_rows:
                m.role_in_project = 'am_stanko_member'
            db.session.commit()
            print(f"✅ Автомиграция: {len(old_rows)} участников переведены "
                  f"из 'am_stanko' в 'am_stanko_member'")

        # Первичный админ
        if not User.query.first():
            admin = User(
                first_name='Иван',
                last_name='Петров',
                company='ООО Рога и Копыта',
                email='admin@example.com',
                role='admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Создан администратор: admin@example.com / admin123")

    # ============================================================
    #  CLI-КОМАНДЫ
    # ============================================================

    @app.cli.command('create-supervisor')
    @click.option('--email', prompt='Email', help='Email нового супервизора')
    @click.option('--first-name', prompt='Имя', help='Имя')
    @click.option('--last-name', prompt='Фамилия', help='Фамилия')
    @click.option('--company', default='—', help='Компания (опц.)')
    @click.option('--password', prompt=True, hide_input=True,
                  confirmation_prompt=True, help='Пароль (мин. 6 символов)')
    def create_supervisor_cli(email, first_name, last_name, company, password):
        """Создать пользователя с ролью 'supervisor' (полный паритет с админом)."""
        email = email.strip().lower()

        if not email or '@' not in email:
            click.echo('❌ Некорректный email')
            return

        if len(password) < 6:
            click.echo('❌ Пароль должен быть не короче 6 символов')
            return

        existing = User.query.filter_by(email=email).first()
        if existing:
            click.echo(f'❌ Пользователь с email {email} уже существует '
                       f'(роль: {existing.role_display})')
            return

        user = User(
            first_name=first_name.strip()[:50],
            last_name=last_name.strip()[:50],
            company=(company or '—').strip()[:100],
            email=email[:100],
            role='supervisor',
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        click.echo()
        click.echo('✅ Супервизор создан:')
        click.echo(f'   ID:        {user.id}')
        click.echo(f'   Имя:       {user.full_name}')
        click.echo(f'   Email:     {user.email}')
        click.echo(f'   Компания:  {user.company}')
        click.echo(f'   Роль:      {user.role_display}')
        click.echo()
        click.echo('🔑 Супервизор имеет полный паритет с администратором:')
        click.echo('   • видит все проекты и пользователей')
        click.echo('   • может ставить задачи от своего имени')
        click.echo('   • может управлять пользователями и справочниками')

    @app.cli.command('set-role')
    @click.option('--email', prompt='Email пользователя', help='Email')
    @click.option('--role', prompt='Роль (user/supervisor/admin)',
                  type=click.Choice(['user', 'supervisor', 'admin']),
                  help='Новая роль')
    def set_role_cli(email, role):
        """Сменить роль существующего пользователя."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            click.echo(f'❌ Пользователь с email {email} не найден')
            return

        # Нельзя понизить последнего админа
        if user.role == 'admin' and role != 'admin':
            admins_count = User.query.filter_by(role='admin', is_active=True).count()
            if admins_count <= 1:
                click.echo('❌ Нельзя понизить последнего администратора системы')
                return

        old_role = user.role
        user.role = role
        db.session.commit()

        click.echo(f'✅ {user.full_name}: {old_role} → {role}')

    @app.cli.command('list-users')
    @click.option('--role', default=None,
                  type=click.Choice(['user', 'supervisor', 'admin']),
                  help='Фильтр по роли')
    def list_users_cli(role):
        """Список пользователей системы."""
        query = User.query
        if role:
            query = query.filter_by(role=role)
        users = query.order_by(User.role, User.last_name).all()

        if not users:
            click.echo('Пользователей не найдено')
            return

        click.echo()
        click.echo(f'{"ID":<5} {"Роль":<12} {"Имя":<30} {"Email":<40} {"Активен":<8}')
        click.echo('-' * 100)
        for u in users:
            active = '✅' if u.is_active else '❌'
            name = f'{u.first_name} {u.last_name}'[:28]
            click.echo(f'{u.id:<5} {u.role:<12} {name:<30} {u.email:<40} {active:<8}')
        click.echo()

    return app


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5001)