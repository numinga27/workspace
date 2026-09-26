"""
Тесты проекта Workspace — все в одном файле.

Запуск:
    pytest test_project.py -v
    python3 test_project.py

Перед запуском убедитесь, что установлены:
    pip install pytest requests
"""
import os
import sys
import tempfile
import secrets
import unittest
from datetime import timedelta
from io import BytesIO

# Чтобы импортировать модули проекта
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Отключаем debug-режим, чтобы ошибки были видны как исключения
os.environ['FLASK_ENV'] = 'testing'
os.environ['SECRET_KEY'] = 'test-secret-key'


# ============================================================
#  БАЗОВЫЙ КЛАСС С ФИКСТУРАМИ
# ============================================================

class BaseTestCase(unittest.TestCase):
    """Общая настройка для всех тестов: временная БД, временный uploads, тестовый клиент."""

    @classmethod
    def setUpClass(cls):
        # Временная БД
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix='.db')
        # Временная папка uploads
        cls.uploads_dir = tempfile.mkdtemp(prefix='ws_uploads_')

        from app import create_app
        from config import Config

        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f'sqlite:///{cls.db_path}'
            UPLOAD_FOLDER = cls.uploads_dir
            WTF_CSRF_ENABLED = False
            SERVER_NAME = 'localhost.localdomain'

        cls.app = create_app(TestConfig)

        # Заполняем БД тестовыми данными
        cls._seed_test_data()

    @classmethod
    def _seed_test_data(cls):
        """Создаём админа, обычного юзера, тестовый проект."""
        from extensions import db
        from models import User, Project, ProjectMember

        with cls.app.app_context():
            # Админ (или создаётся при init БД, или добавляем)
            admin = User.query.filter_by(email='admin@example.com').first()
            if not admin:
                admin = User(
                    first_name='Иван', last_name='Петров',
                    company='ООО Рога и Копыта',
                    email='admin@example.com', role='admin'
                )
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()

            # Тестовый проект
            project = Project(name='TestProject', created_by=admin.id)
            db.session.add(project)
            db.session.commit()
            db.session.add(ProjectMember(
                user_id=admin.id, project_id=project.id, role_in_project='admin'
            ))
            db.session.commit()
            cls.test_project_id = project.id
            cls.admin_id = admin.id

            # Тестовый сотрудник с русской фамилией (для PDF)
            emp_email = f'employee_{secrets.token_hex(4)}@example.com'
            employee = User(
                first_name='Пётр', last_name='Сидоров',
                company='ООО Тест', email=emp_email, role='user'
            )
            employee.set_password('employee123')
            db.session.add(employee)
            db.session.commit()
            db.session.add(ProjectMember(
                user_id=employee.id, project_id=project.id, role_in_project='member'
            ))
            db.session.commit()
            cls.employee_id = employee.id
            cls.employee_email = emp_email

    @classmethod
    def tearDownClass(cls):
        os.close(cls.db_fd)
        os.unlink(cls.db_path)
        import shutil
        shutil.rmtree(cls.uploads_dir, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()
        self.client.post('/login', data={
            'email': 'admin@example.com',
            'password': 'admin123',
        })

    def tearDown(self):
        """Чистим созданные в тесте объекты."""
        pass


# ============================================================
#  SMOKE: ПРИЛОЖЕНИЕ И BLUEPRINTS
# ============================================================

class TestSmoke(BaseTestCase):

    def test_01_app_created(self):
        """Приложение создано."""
        self.assertIsNotNone(self.app)

    def test_02_blueprints_registered(self):
        """Все ожидаемые blueprints зарегистрированы."""
        expected = {'auth', 'dashboard', 'tasks', 'projects', 'todos',
                    'reports', 'files', 'chat', 'calendar', 'customers',
                    'team', 'pdf', 'admin'}
        registered = set(self.app.blueprints.keys())
        missing = expected - registered
        self.assertFalse(missing, f"Не зарегистрированы: {missing}")

    def test_03_critical_urls_exist(self):
        """Ключевые URL присутствуют."""
        urls = {rule.rule for rule in self.app.url_map.iter_rules()}
        must_have = [
            '/login', '/register', '/logout', '/dashboard',
            '/my-tasks', '/my-calendar', '/customers',
            '/project/create',
            '/project/<int:project_id>',
            '/task/<int:task_id>',
            '/project/<int:project_id>/report/pdf',
            '/task/<int:task_id>/report/pdf',
            '/project/<int:project_id>/employee/<int:user_id>/pdf',
        ]
        for url in must_have:
            self.assertIn(url, urls, f"URL {url} не зарегистрирован")

    def test_04_no_duplicate_endpoints(self):
        """Нет дублирующихся эндпоинтов."""
        endpoints = [rule.endpoint for rule in self.app.url_map.iter_rules()]
        duplicates = {e for e in endpoints if endpoints.count(e) > 1}
        self.assertFalse(duplicates, f"Дубли: {duplicates}")

    def test_05_db_tables(self):
        """Все таблицы созданы."""
        from extensions import db
        from sqlalchemy import inspect
        with self.app.app_context():
            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
        expected = {
            'user', 'customer', 'project', 'milestone', 'project_member',
            'task', 'todo', 'event', 'report', 'message', 'message_read',
            'folder', 'file', 'invitation'
        }
        missing = expected - tables
        self.assertFalse(missing, f"Нет таблиц: {missing}")

    def test_06_admin_password_hashed(self):
        """Пароль админа в хешированном виде."""
        from models import User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            self.assertIsNotNone(admin)
            self.assertTrue(admin.password.startswith('pbkdf2:sha256'),
                            "Пароль админа не захеширован")

    def test_07_set_and_check_password(self):
        """set_password / check_password."""
        from models import User
        with self.app.app_context():
            u = User(first_name='X', last_name='Y', company='Z',
                     email='hashtest@example.com')
            u.set_password('secret123')
            self.assertNotEqual(u.password, 'secret123')
            self.assertTrue(u.check_password('secret123'))
            self.assertFalse(u.check_password('wrong'))


# ============================================================
#  АВТОРИЗАЦИЯ
# ============================================================

class TestAuth(BaseTestCase):

    def test_01_login_page(self):
        """Страница /login открывается."""
        r = self.app.test_client().get('/login')
        self.assertEqual(r.status_code, 200)

    def test_02_login_valid(self):
        """Логин валидными данными."""
        c = self.app.test_client()
        r = c.post('/login', data={
            'email': 'admin@example.com', 'password': 'admin123'
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/dashboard', r.location)

    def test_03_login_wrong_password(self):
        """Логин с неверным паролем."""
        c = self.app.test_client()
        r = c.post('/login', data={
            'email': 'admin@example.com', 'password': 'wrong'
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'\xd0\x9d\xd0\xb5\xd0\xb2\xd0\xb5\xd1\x80\xd0\xbd\xd1\x8b\xd0\xb9',
                      r.data, "Ожидалось 'Неверный'")

    def test_04_login_unknown_email(self):
        """Логин с неизвестным email."""
        c = self.app.test_client()
        r = c.post('/login', data={
            'email': 'nobody@nowhere.com', 'password': 'x'
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)

    def test_05_logout(self):
        """Логаут."""
        c = self.app.test_client()
        c.post('/login', data={'email': 'admin@example.com', 'password': 'admin123'})
        r = c.get('/logout', follow_redirects=False)
        self.assertEqual(r.status_code, 302)

    def test_06_dashboard_without_login_redirects(self):
        """Без логина /dashboard редиректит на /login."""
        c = self.app.test_client()
        r = c.get('/dashboard', follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.location)

    def test_07_register_new_user(self):
        """Регистрация нового пользователя."""
        c = self.app.test_client()
        email = f'reg_{secrets.token_hex(4)}@example.com'
        r = c.post('/register', data={
            'first_name': 'New', 'last_name': 'User',
            'company': 'NewCorp', 'email': email,
            'password': 'newpass123'
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        from models import User
        with self.app.app_context():
            u = User.query.filter_by(email=email).first()
            self.assertIsNotNone(u)
            self.assertTrue(u.password.startswith('pbkdf2:sha256'))

    def test_08_plain_password_migration(self):
        """Старый plain-text пароль перехешируется при логине."""
        from extensions import db
        from models import User

        email = f'legacy_{secrets.token_hex(4)}@example.com'
        with self.app.app_context():
            u = User(first_name='L', last_name='O', company='X',
                     email=email, password='plainpass123', role='user')
            db.session.add(u)
            db.session.commit()

        c = self.app.test_client()
        r = c.post('/login', data={'email': email, 'password': 'plainpass123'},
                   follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        with self.app.app_context():
            u = User.query.filter_by(email=email).first()
            self.assertTrue(u.password.startswith('pbkdf2:sha256'),
                            "Пароль не перехешировался")


# ============================================================
#  МОДЕЛИ
# ============================================================

class TestModels(BaseTestCase):

    def test_01_utcnow_naive(self):
        """utcnow возвращает naive datetime."""
        from utils import utcnow
        self.assertIsNone(utcnow().tzinfo)

    def test_02_project_completion_percentage(self):
        """completion_percentage считает правильно."""
        from extensions import db
        from models import Project, Task, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='PctTest', created_by=admin.id)
            db.session.add(p); db.session.commit()

            for title, status in [('A', 'completed'), ('B', 'in_progress'), ('C', 'new')]:
                db.session.add(Task(title=title, project_id=p.id,
                                    created_by=admin.id, status=status))
            db.session.commit()
            self.assertEqual(p.completion_percentage, 33)

            db.session.delete(p); db.session.commit()

    def test_03_task_is_overdue(self):
        """is_overdue правильно определяется."""
        from extensions import db
        from models import Project, Task, User
        from utils import utcnow
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='OvTest', created_by=admin.id)
            db.session.add(p); db.session.commit()

            t = Task(title='Old', project_id=p.id, created_by=admin.id,
                     due_date=utcnow() - timedelta(days=5), status='in_progress')
            db.session.add(t); db.session.commit()
            self.assertTrue(t.is_overdue)
            self.assertGreaterEqual(t.days_overdue, 5)

            t.status = 'completed'; db.session.commit()
            self.assertFalse(t.is_overdue)

            db.session.delete(p); db.session.commit()

    def test_04_task_no_due_date(self):
        """Задача без due_date не просрочена."""
        from extensions import db
        from models import Project, Task, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='NoDue', created_by=admin.id)
            db.session.add(p); db.session.commit()
            t = Task(title='X', project_id=p.id, created_by=admin.id)
            db.session.add(t); db.session.commit()
            self.assertFalse(t.is_overdue)
            db.session.delete(p); db.session.commit()

    def test_05_todo_status_key(self):
        """Todo.status_key правильно определяется."""
        from extensions import db
        from models import Project, Todo, User
        from utils import utcnow
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='TodoTest', created_by=admin.id)
            db.session.add(p); db.session.commit()

            t = Todo(title='T', project_id=p.id, created_by=admin.id)
            db.session.add(t); db.session.commit()
            self.assertEqual(t.status_key, 'new')

            t.due_date = utcnow() - timedelta(days=2); db.session.commit()
            self.assertEqual(t.status_key, 'overdue')

            t.is_done = True; db.session.commit()
            self.assertEqual(t.status_key, 'done')

            db.session.delete(p); db.session.commit()

    def test_06_role_display(self):
        """ProjectMember.role_display переводит роли."""
        from extensions import db
        from models import Project, ProjectMember, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='RoleTest', created_by=admin.id)
            db.session.add(p); db.session.commit()
            m = ProjectMember(user_id=admin.id, project_id=p.id, role_in_project='manager')
            db.session.add(m); db.session.commit()
            self.assertEqual(m.role_display, 'Менеджер')
            db.session.delete(p); db.session.commit()

    def test_07_report_reason_display(self):
        """Report.reason_display / reason_color."""
        from extensions import db
        from models import Project, Report, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='RepTest', created_by=admin.id)
            db.session.add(p); db.session.commit()
            r = Report(title='R', project_id=p.id, author_id=admin.id,
                       reason='force_majeure')
            db.session.add(r); db.session.commit()
            self.assertEqual(r.reason_display[0], 'Форс-мажор')
            self.assertEqual(r.reason_color, 'danger')
            db.session.delete(p); db.session.commit()


# ============================================================
#  СТРАНИЦЫ: ОБХОД ВСЕХ URL
# ============================================================

class TestPages(BaseTestCase):

    def test_01_public_pages(self):
        """Публичные страницы."""
        c = self.app.test_client()
        for path in ['/login', '/register']:
            r = c.get(path)
            self.assertEqual(r.status_code, 200, f"{path} → {r.status_code}")

    def test_02_admin_pages(self):
        """Страницы, требующие логина."""
        pages = [
            '/dashboard',
            '/my-tasks',
            '/my-calendar',
            '/customers',
            '/project/create',
            '/customer/create',
        ]
        for path in pages:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} → {r.status_code}")

    def test_03_json_endpoints(self):
        """JSON-эндпоинты."""
        r = self.client.get('/my-calendar/events.json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.is_json)

    def test_04_project_pages(self):
        """Все вкладки проекта."""
        pid = self.test_project_id
        pages = [
            f'/project/{pid}',
            f'/project/{pid}/edit',
            f'/project/{pid}/settings',
            f'/project/{pid}/events.json',
        ]
        for path in pages:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} → {r.status_code}")

    def test_05_all_get_urls_no_500(self):
        """Обходим ВСЕ GET-эндпоинты без параметров — 500 быть не должно."""
        skip_endpoints = {'static', 'admin.manual_send_notifications'}
        failed = []
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint in skip_endpoints:
                continue
            if 'GET' not in rule.methods:
                continue
            if '<' in rule.rule:
                continue  # динамические пропускаем
            try:
                r = self.client.get(rule.rule)
                if r.status_code == 500:
                    failed.append((rule.rule, rule.endpoint, r.status_code))
            except Exception as e:
                failed.append((rule.rule, rule.endpoint, str(e)))
        if failed:
            msg = "\n".join(f"  {p} ({e}) → {s}" for p, e, s in failed)
            self.fail(f"Есть падающие страницы:\n{msg}")


# ============================================================
#  ПРОЕКТЫ
# ============================================================

class TestProjects(BaseTestCase):

    def test_01_create_project(self):
        """Создание проекта."""
        r = self.client.post('/project/create', data={
            'name': 'CreatedInTest',
            'description': 'desc',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        from models import Project, ProjectMember, User
        with self.app.app_context():
            p = Project.query.filter_by(name='CreatedInTest').first()
            self.assertIsNotNone(p)
            admin = User.query.filter_by(email='admin@example.com').first()
            m = ProjectMember.query.filter_by(user_id=admin.id, project_id=p.id).first()
            self.assertIsNotNone(m)
            self.assertEqual(m.role_in_project, 'admin')
            # cleanup
            from extensions import db
            db.session.delete(p); db.session.commit()

    def test_02_delete_requires_confirmation(self):
        """Удаление проекта требует слово УДАЛИТЬ."""
        from extensions import db
        from models import Project, ProjectMember, User

        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            p = Project(name='ToDeleteTest', created_by=admin.id)
            db.session.add(p); db.session.commit()
            db.session.add(ProjectMember(user_id=admin.id, project_id=p.id,
                                         role_in_project='admin'))
            db.session.commit()
            pid = p.id

        # Неверное слово
        r = self.client.post(f'/project/{pid}/delete',
                             data={'confirm_text': 'wrong'},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(Project.query.get(pid),
                                 "Проект удалился без подтверждения")

        # Верное слово
        r = self.client.post(f'/project/{pid}/delete',
                             data={'confirm_text': 'УДАЛИТЬ'},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(Project.query.get(pid),
                              "Проект не удалился")


# ============================================================
#  ЗАДАЧИ
# ============================================================

class TestTasks(BaseTestCase):

    def test_01_create_task(self):
        """Создание задачи с валидным исполнителем."""
        r = self.client.post(
            f'/project/{self.test_project_id}/task/create',
            data={
                'title': 'TaskCreatedInTest',
                'assigned_to': str(self.employee_id),
                'due_date': '2026-12-31',
            },
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

        from models import Task
        with self.app.app_context():
            t = Task.query.filter_by(title='TaskCreatedInTest').first()
            self.assertIsNotNone(t)
            self.assertEqual(t.project_id, self.test_project_id)
            self.assertEqual(t.assigned_to, self.employee_id)
            from extensions import db
            db.session.delete(t); db.session.commit()

    def test_02_create_task_invalid_assignee(self):
        """Невалидный исполнитель — задача не создаётся."""
        r = self.client.post(
            f'/project/{self.test_project_id}/task/create',
            data={'title': 'InvalidAssignee', 'assigned_to': '99999'},
            follow_redirects=False,
        )
        from models import Task
        with self.app.app_context():
            t = Task.query.filter_by(title='InvalidAssignee').first()
            self.assertIsNone(t, "Задача создана с невалидным исполнителем")

    def test_03_update_task_status(self):
        """Смена статуса задачи."""
        from extensions import db
        from models import Task, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            t = Task(title='StatusTest', project_id=self.test_project_id,
                     created_by=admin.id, status='new')
            db.session.add(t); db.session.commit()
            tid = t.id

        r = self.client.post(f'/task/{tid}/update_status',
                             data={'status': 'completed'},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            t = Task.query.get(tid)
            self.assertEqual(t.status, 'completed')
            db.session.delete(t); db.session.commit()

    def test_04_task_overdue_comment(self):
        """Комментарий к просроченной задаче."""
        from extensions import db
        from models import Task, User
        from utils import utcnow
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            t = Task(title='CommentTest', project_id=self.test_project_id,
                     created_by=admin.id, assigned_to=self.employee_id,
                     status='in_progress',
                     due_date=utcnow() - timedelta(days=3))
            db.session.add(t); db.session.commit()
            tid = t.id

        r = self.client.post(f'/task/{tid}/comment',
                             data={'comment': 'Задержка поставки'},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            t = Task.query.get(tid)
            self.assertEqual(t.comment, 'Задержка поставки')
            db.session.delete(t); db.session.commit()

    def test_05_task_detail_page(self):
        """Открытие страницы задачи."""
        from extensions import db
        from models import Task, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            t = Task(title='PageTest', project_id=self.test_project_id,
                     created_by=admin.id)
            db.session.add(t); db.session.commit()
            tid = t.id

        r = self.client.get(f'/task/{tid}')
        self.assertEqual(r.status_code, 200)

        with self.app.app_context():
            t = Task.query.get(tid)
            db.session.delete(t); db.session.commit()


# ============================================================
#  PDF-ОТЧЁТЫ
# ============================================================

class TestPDF(BaseTestCase):

    def test_01_project_pdf(self):
        """PDF-отчёт по проекту."""
        r = self.client.get(f'/project/{self.test_project_id}/report/pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Type'), 'application/pdf')
        self.assertEqual(r.data[:4], b'%PDF')

    def test_02_task_pdf(self):
        """PDF-отчёт по задаче."""
        from extensions import db
        from models import Task, User
        with self.app.app_context():
            admin = User.query.filter_by(email='admin@example.com').first()
            t = Task(title='TaskForPDF', project_id=self.test_project_id,
                     created_by=admin.id, assigned_to=self.employee_id)
            db.session.add(t); db.session.commit()
            tid = t.id

        r = self.client.get(f'/task/{tid}/report/pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[:4], b'%PDF')

        with self.app.app_context():
            t = Task.query.get(tid)
            db.session.delete(t); db.session.commit()

    def test_03_employee_pdf_with_cyrillic(self):
        """PDF по сотруднику с русской фамилией — UnicodeEncodeError не должно быть."""
        r = self.client.get(
            f'/project/{self.test_project_id}/employee/{self.employee_id}/pdf'
        )
        self.assertEqual(r.status_code, 200, "PDF по сотруднику упал")
        self.assertEqual(r.data[:4], b'%PDF')

        cd = r.headers.get('Content-Disposition', '')
        self.assertIn('filename*=', cd,
                      "В Content-Disposition нет UTF-8 filename")


# ============================================================
#  ТОЧКА ВХОДА
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)