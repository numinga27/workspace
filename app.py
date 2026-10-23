from flask import Flask
from datetime import datetime, timezone
import click

from config import Config
from extensions import db, mail, FLASK_MAIL_AVAILABLE, cache
from models import User
from blueprints import register_blueprints


# ============================================================
#  ИНИЦИАЛИЗАЦИЯ CELERY
# ============================================================

def celery_init_app(app):
    """Создает и настраивает Celery, привязанный к Flask-приложению."""
    from celery import Celery, Task

    class FlaskTask(Task):
        """Задача, которая выполняется в контексте Flask-приложения."""
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app


# ============================================================
#  ХЕЛПЕРЫ ДЛЯ CONTEXT PROCESSORS
# ============================================================

def _utcnow():
    return datetime.now(timezone.utc)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- Настройка Celery (прямое присваивание, чтобы перезаписать любые старые настройки) ---
    app.config['CELERY'] = {
        'broker_url': 'redis://localhost:6379/0',
        'result_backend': 'redis://localhost:6379/0',
        'task_ignore_result': True,
    }

    # --- Инициализация расширений ---
    db.init_app(app)
    
    # --- Инициализация кэша ---
    if cache:
        app.config.setdefault('CACHE_TYPE', 'SimpleCache')
        app.config.setdefault('CACHE_DEFAULT_TIMEOUT', 60)
        cache.init_app(app)

    if FLASK_MAIL_AVAILABLE and mail is not None:
        mail.init_app(app)

    # --- Инициализация Celery ---
    celery_init_app(app)

    # --- Регистрация Blueprints ---
    register_blueprints(app)

    # ============================================================
    #  CONTEXT PROCESSORS
    # ============================================================

    @app.context_processor
    def inject_unread_counts():
        from flask import session
        from utils import get_unread_counts
        if 'user_id' in session:
            try:
                return {'unread_counts': get_unread_counts(session['user_id'])}
            except Exception as e:
                print(f'⚠️ Ошибка get_unread_counts: {e}')
        return {'unread_counts': {}}

    @app.context_processor
    def inject_overdue_count():
        from flask import session
        from utils import get_overdue_tasks_count
        if 'user_id' in session:
            try:
                return {'my_overdue_count': get_overdue_tasks_count(session['user_id'])}
            except Exception as e:
                print(f'⚠️ Ошибка подсчёта просроченных: {e}')
        return {'my_overdue_count': 0}

    @app.context_processor
    def inject_unread_tasks_count():
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

    @app.context_processor
    def inject_support_unread():
        from flask import session
        from utils import get_support_unread_count
        if 'user_id' in session:
            try:
                return {'support_unread_count': get_support_unread_count(session['user_id'])}
            except Exception as e:
                print(f'⚠️ Ошибка support_unread_count: {e}')
        return {'support_unread_count': 0}

    # ============================================================
    #  СОЗДАНИЕ ТАБЛИЦ И SEED ГЛАВНОГО АДМИНА
    # ============================================================

    with app.app_context():
        db.create_all()

        from models import ProjectMember
        old_rows = ProjectMember.query.filter_by(role_in_project='am_stanko').all()
        if old_rows:
            for m in old_rows:
                m.role_in_project = 'am_stanko_member'
            db.session.commit()
            print(f"✅ Автомиграция: {len(old_rows)} участников переведены "
                  f"из 'am_stanko' в 'am_stanko_member'")

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
    #  ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ ОШИБОК
    # ============================================================

    @app.errorhandler(500)
    def handle_500(e):
        """Внутренняя ошибка сервера — показываем заглушку,
        создаём тикет в поддержке и отправляем Push админам."""
        import traceback
        from flask import request, session

        app.logger.error('❌ Ошибка 500:', exc_info=True)

        try:
            error_traceback = traceback.format_exc()
            user_info = "Аноним"
            if 'user_id' in session:
                user = User.query.get(session['user_id'])
                if user:
                    user_info = f"{user.full_name} ({user.email})"

            from services.support_errors import create_error_ticket
            ticket_id = create_error_ticket(
                url=request.url,
                method=request.method,
                user_info=user_info,
                traceback_text=error_traceback,
            )

            if ticket_id:
                from models import SupportTicket, SupportMessage
                from services.push import notify_new_support_message
                from services.tasks import send_push_async

                ticket = SupportTicket.query.get(ticket_id)
                if ticket:
                    msg = ticket.messages.order_by(
                        SupportMessage.created_at.desc()
                    ).first()
                    if msg:
                        push_data_list = notify_new_support_message(
                            ticket, msg, for_admin=True
                        )
                        if push_data_list:
                            for push_data in push_data_list:
                                send_push_async.delay(**push_data)

        except Exception as notify_error:
            app.logger.error(f'⚠️ Не удалось создать тикет об ошибке: {notify_error}')

        try:
            from flask import render_template
            return render_template('errors/500.html'), 500
        except Exception:
            return (
                '<!DOCTYPE html><html><head><meta charset="UTF-8">'
                '<title>Сервер на обслуживании</title>'
                '<style>body{font-family:sans-serif;text-align:center;padding:80px 20px;'
                'background:#f5f7fb;color:#0d0d12;}h1{color:#5b5bd6;}</style></head>'
                '<body><h1>🛠 Сервер на техническом обслуживании</h1>'
                '<p>Мы улучшаем сервис. Потерпите немного — скоро всё заработает.</p>'
                '<p><a href="/dashboard" style="color:#5b5bd6;">Обновить</a></p></body></html>',
                500
            )

    @app.errorhandler(404)
    def handle_404(e):
        try:
            from flask import render_template
            return render_template('errors/404.html'), 404
        except Exception:
            return (
                '<!DOCTYPE html><html><head><meta charset="UTF-8">'
                '<title>Страница не найдена</title></head>'
                '<body style="font-family:sans-serif;text-align:center;padding:80px;">'
                '<h1>🔍 Страница не найдена</h1>'
                '<p><a href="/dashboard">На главную</a></p></body></html>',
                404
            )

    @app.errorhandler(403)
    def handle_403(e):
        try:
            from flask import render_template
            return render_template('errors/404.html'), 403
        except Exception:
            return '<h1>403 — Доступ запрещён</h1>', 403

    # ============================================================
    #  PWA: манифест и Service Worker
    # ============================================================

    @app.route('/manifest.json')
    def pwa_manifest():
        from flask import send_from_directory, make_response
        response = make_response(send_from_directory(
            'static', 'manifest.json',
            mimetype='application/manifest+json'
        ))
        response.headers['Content-Type'] = 'application/manifest+json; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.route('/service-worker.js')
    def pwa_service_worker():
        from flask import send_from_directory, make_response
        response = make_response(send_from_directory(
            'static', 'service-worker.js',
            mimetype='application/javascript'
        ))
        response.headers.pop('Content-Disposition', None)
        response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/sw.js')
    def pwa_sw():
        from flask import send_from_directory, make_response
        response = make_response(send_from_directory(
            'static', 'sw.js',
            mimetype='application/javascript'
        ))
        response.headers.pop('Content-Disposition', None)
        response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    # ============================================================
    #  WEB PUSH: подписка / отписка / VAPID-ключ
    # ============================================================

    @app.route('/push/vapid-public-key')
    def push_vapid_public_key():
        from flask import jsonify
        return jsonify({
            'publicKey': app.config.get('VAPID_PUBLIC_KEY', '')
        })

    @app.route('/push/subscribe', methods=['POST'])
    def push_subscribe():
        from flask import request, jsonify, session
        from models import PushSubscription

        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401

        data = request.get_json(silent=True) or {}
        endpoint = data.get('endpoint')
        keys = data.get('keys') or {}
        p256dh = keys.get('p256dh')
        auth = keys.get('auth')

        if not endpoint or not p256dh or not auth:
            return jsonify({'ok': False, 'error': 'invalid_payload'}), 400

        user_id = session['user_id']

        sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
        if sub:
            sub.user_id = user_id
            sub.p256dh = p256dh
            sub.auth = auth
            sub.is_active = True
            sub.user_agent = (request.headers.get('User-Agent') or '')[:255]
        else:
            sub = PushSubscription(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=(request.headers.get('User-Agent') or '')[:255],
                is_active=True,
            )
            db.session.add(sub)

        db.session.commit()
        return jsonify({'ok': True, 'subscription_id': sub.id})

    @app.route('/push/unsubscribe', methods=['POST'])
    def push_unsubscribe():
        from flask import request, jsonify, session
        from models import PushSubscription

        if 'user_id' not in session:
            return jsonify({'ok': False}), 401

        data = request.get_json(silent=True) or {}
        endpoint = data.get('endpoint')

        if endpoint:
            sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
            if sub and sub.user_id == session['user_id']:
                sub.is_active = False
                db.session.commit()

        return jsonify({'ok': True})

    @app.route('/push/test', methods=['POST'])
    def push_test():
        from flask import jsonify, session
        from services.push import send_push_to_user

        if 'user_id' not in session:
            return jsonify({'ok': False}), 401

        sent = send_push_to_user(
            user_id=session['user_id'],
            title='🎉 Тест уведомлений',
            body='Если видишь это — Web Push работает!',
            url='/dashboard',
            tag='test-1',
        )
        return jsonify({'ok': True, 'sent': sent})

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
        """Создать пользователя с ролью 'supervisor'."""
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

    @app.cli.command('test-push')
    @click.option('--email', prompt='Email получателя',
                  help='Кому отправить тестовый push')
    def test_push_cli(email):
        """Отправить тестовый push-уведомление пользователю."""
        from services.push import send_push_to_user

        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            click.echo(f'❌ Пользователь с email {email} не найден')
            return

        sent = send_push_to_user(
            user_id=user.id,
            title='🎉 Тест push',
            body=f'Привет, {user.first_name}! Push работает.',
            url='/dashboard',
            tag='cli-test',
        )

        click.echo()
        click.echo(f'📤 Отправлено: {sent} подписок')
        if sent == 0:
            click.echo('⚠️ Возможно, у пользователя нет активных подписок.')
            click.echo('   Пусть откроет PWA на iPhone и разрешит уведомления.')
        else:
            click.echo('✅ Проверь уведомление на устройстве.')

    return app


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5001)