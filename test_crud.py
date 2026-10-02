"""
Smoke-тесты CRUD на реальной БД (workspace_prod).

Запуск на сервере:
    cd ~/workspace && source venv/bin/activate
    TEST_DATABASE_URL='postgresql://workspace_user:wspass2026@localhost:5432/workspace_prod' \
      python test_crud.py

ВНИМАНИЕ: тесты пишут в указанную БД. Убедись, что TEST_DATABASE_URL
указывает туда, куда хочешь (по умолчанию — workspace_prod).

Все тестовые данные помечаются префиксом CRUDTest_ и удаляются
в tearDown. Если что-то осталось — см. cleanup в конце файла.
"""
import os
import sys
import tempfile
import secrets
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

os.environ.setdefault('FLASK_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')

TEST_PREFIX = 'CRUDTest_'


# ============================================================
#  БАЗОВЫЙ КЛАСС
# ============================================================

class BaseCrudTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.uploads_dir = tempfile.mkdtemp(prefix='ws_uploads_crud_')

        test_db_url = os.environ.get('TEST_DATABASE_URL')
        if not test_db_url:
            # Фолбэк: временный SQLite, чтобы случайно не писать в прод
            cls.db_fd, cls.db_path = tempfile.mkstemp(suffix='.db')
            test_db_url = f'sqlite:///{cls.db_path}'
            print(f"\n⚠️  TEST_DATABASE_URL не задан — используется временный SQLite\n")
        else:
            cls.db_fd, cls.db_path = None, None
            print(f"\n⚠️  Тесты пишут в БД: {test_db_url.split('@')[-1] if '@' in test_db_url else test_db_url}\n")

        from app import create_app
        from config import Config

        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = test_db_url
            UPLOAD_FOLDER = cls.uploads_dir
            WTF_CSRF_ENABLED = False
            SECRET_KEY = 'crud-test-secret'

        cls.app = create_app(TestConfig)
        cls._seed()

    @classmethod
    def _seed(cls):
        """Создаём тестового админа (если ещё нет)."""
        from extensions import db
        from models import User

        with cls.app.app_context():
            admin = User.query.filter_by(email='crud_admin@test.local').first()
            if not admin:
                admin = User(
                    first_name='CRUD', last_name='Admin',
                    company='TestCorp', email='crud_admin@test.local',
                    role='admin',
                )
                admin.set_password('crud123')
                db.session.add(admin)
                db.session.commit()
            cls.admin_id = admin.id

    @classmethod
    def tearDownClass(cls):
        if cls.db_fd is not None:
            try:
                os.close(cls.db_fd)
            except OSError:
                pass
        if cls.db_path:
            try:
                os.unlink(cls.db_path)
            except OSError:
                pass
        import shutil
        shutil.rmtree(cls.uploads_dir, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()
        self.client.post('/login', data={
            'email': 'crud_admin@test.local',
            'password': 'crud123',
        })

    def _uid(self):
        return secrets.token_hex(4)

    def _name(self, base='Item'):
        """Возвращает имя с тестовым префиксом."""
        return f'{TEST_PREFIX}{base}_{self._uid()}'


# ============================================================
#  1. SEQUENCES
# ============================================================

class TestSequences(BaseCrudTestCase):

    def test_01_all_tables_have_serial_default(self):
        """Все таблицы с id должны иметь DEFAULT nextval(...)."""
        from extensions import db
        from sqlalchemy import text

        with self.app.app_context():
            # Проверка драйвера внутри контекста
            if not db.engine.url.drivername.startswith('postgresql'):
                self.skipTest('Тест специфичен для PostgreSQL')

            rows = db.session.execute(text("""
                SELECT c.table_name
                FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                AND c.column_name = 'id'
                AND c.column_default IS NULL
                AND c.table_name IN (
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_type = 'BASE TABLE'
                )
            """)).fetchall()

        missing = [r[0] for r in rows]
        self.assertFalse(
            missing,
            f"\nТаблицы без DEFAULT nextval на id: {missing}\n"
            f"INSERT упадёт с NotNullViolation. Запусти fix-sequences.sql."
        )

    def test_02_insert_new_row_gets_id(self):
        """INSERT получает id автоматически."""
        from extensions import db
        from models import Customer

        name = self._name('SeqTest')
        with self.app.app_context():
            c = Customer(name=name)
            db.session.add(c)
            db.session.commit()
            cid = c.id
            self.assertIsNotNone(cid)
            self.assertGreater(cid, 0)

            # cleanup
            db.session.delete(c)
            db.session.commit()


# ============================================================
#  2. PROJECT
# ============================================================

class TestProjectCrud(BaseCrudTestCase):

    def test_01_create_project_minimal(self):
        name = self._name('Project')
        r = self.client.post('/project/create', data={
            'name': name,
            'description': 'Описание',
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        from extensions import db
        from models import Project

        with self.app.app_context():
            p = Project.query.filter_by(name=name).first()
            self.assertIsNotNone(p)
            self.assertIsNotNone(p.id)
            self.assertEqual(p.created_by, self.admin_id)

            # cleanup
            db.session.delete(p)
            db.session.commit()


# ============================================================
#  3. TASK
# ============================================================

class TestTaskCrud(BaseCrudTestCase):

    def _make_project(self):
        """Создать проект и вернуть его id."""
        from extensions import db
        from models import Project, ProjectMember

        name = self._name('TaskProj')
        with self.app.app_context():
            p = Project(name=name, created_by=self.admin_id)
            db.session.add(p)
            db.session.commit()
            db.session.add(ProjectMember(
                user_id=self.admin_id, project_id=p.id, role_in_project='admin',
            ))
            db.session.commit()
            return p.id

    def _cleanup_project(self, project_id):
        from extensions import db
        from models import Project
        with self.app.app_context():
            p = Project.query.get(project_id)
            if p:
                db.session.delete(p)
                db.session.commit()

    def test_01_create_task_minimal(self):
        pid = self._make_project()
        title = self._name('Task')

        r = self.client.post(
            f'/project/{pid}/task/create',
            data={'title': title},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

        from models import Task
        with self.app.app_context():
            t = Task.query.filter_by(title=title).first()
            self.assertIsNotNone(t)
            self.assertIsNotNone(t.id)

        self._cleanup_project(pid)

    def test_02_create_task_with_due_date(self):
        pid = self._make_project()
        title = self._name('TaskDue')

        r = self.client.post(
            f'/project/{pid}/task/create',
            data={'title': title, 'due_date': '2026-12-31'},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

        from models import Task
        with self.app.app_context():
            t = Task.query.filter_by(title=title).first()
            self.assertIsNotNone(t)
            self.assertIsNotNone(t.due_date)
            # проверка, что is_overdue не падает
            self.assertFalse(t.is_overdue)

        self._cleanup_project(pid)


# ============================================================
#  4. TODO
# ============================================================

class TestTodoCrud(BaseCrudTestCase):

    def _make_project(self):
        from extensions import db
        from models import Project, ProjectMember

        name = self._name('TodoProj')
        with self.app.app_context():
            p = Project(name=name, created_by=self.admin_id)
            db.session.add(p)
            db.session.commit()
            db.session.add(ProjectMember(
                user_id=self.admin_id, project_id=p.id, role_in_project='admin',
            ))
            db.session.commit()
            return p.id

    def _cleanup_project(self, project_id):
        from extensions import db
        from models import Project
        with self.app.app_context():
            p = Project.query.get(project_id)
            if p:
                db.session.delete(p)
                db.session.commit()

    def test_01_create_todo(self):
        pid = self._make_project()
        title = self._name('Todo')

        r = self.client.post(
            f'/project/{pid}/todo/create',
            data={'title': title},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

        from models import Todo
        with self.app.app_context():
            t = Todo.query.filter_by(title=title).first()
            self.assertIsNotNone(t)
            self.assertIsNotNone(t.id)

        self._cleanup_project(pid)


# ============================================================
#  5. CUSTOMER + CONTACT
# ============================================================

class TestCustomerCrud(BaseCrudTestCase):

    def test_01_create_customer(self):
        name = self._name('Customer')
        r = self.client.post('/customer/create', data={
            'name': name,
            'inn': '1234567890',
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        from extensions import db
        from models import Customer
        with self.app.app_context():
            c = Customer.query.filter_by(name=name).first()
            self.assertIsNotNone(c)
            self.assertIsNotNone(c.id)

            db.session.delete(c)
            db.session.commit()


# ============================================================
#  6. SUPPLIER + SUBCONTRACTOR
# ============================================================

class TestSupplierCrud(BaseCrudTestCase):

    def test_01_create_supplier(self):
        name = self._name('Supplier')
        r = self.client.post('/supplier/create', data={
            'name': name,
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        from extensions import db
        from models import Supplier
        with self.app.app_context():
            s = Supplier.query.filter_by(name=name).first()
            self.assertIsNotNone(s)
            self.assertEqual(s.supplier_type, 'supplier')

            db.session.delete(s)
            db.session.commit()

    def test_02_create_subcontractor(self):
        name = self._name('Subcontractor')
        r = self.client.post('/subcontractor/create', data={
            'name': name,
        }, follow_redirects=False)
        self.assertEqual(r.status_code, 302)

        from extensions import db
        from models import Supplier
        with self.app.app_context():
            s = Supplier.query.filter_by(name=name).first()
            self.assertIsNotNone(s)
            self.assertEqual(s.supplier_type, 'subcontractor')

            db.session.delete(s)
            db.session.commit()


# ============================================================
#  7. MILESTONE
# ============================================================

class TestMilestoneCrud(BaseCrudTestCase):

    def _make_project(self):
        from extensions import db
        from models import Project, ProjectMember

        name = self._name('MsProj')
        with self.app.app_context():
            p = Project(name=name, created_by=self.admin_id)
            db.session.add(p)
            db.session.commit()
            db.session.add(ProjectMember(
                user_id=self.admin_id, project_id=p.id, role_in_project='admin',
            ))
            db.session.commit()
            return p.id

    def _cleanup_project(self, project_id):
        from extensions import db
        from models import Project
        with self.app.app_context():
            p = Project.query.get(project_id)
            if p:
                db.session.delete(p)
                db.session.commit()

    def test_01_create_milestone(self):
        pid = self._make_project()
        name = self._name('Milestone')

        r = self.client.post(
            f'/project/{pid}/milestone/create',
            data={'name': name, 'due_date': '2026-12-31'},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

        from models import Milestone
        with self.app.app_context():
            m = Milestone.query.filter_by(name=name).first()
            self.assertIsNotNone(m)
            self.assertIsNotNone(m.id)

        self._cleanup_project(pid)


# ============================================================
#  ТОЧКА ВХОДА + ПОДСКАЗКА ПО ОЧИСТКЕ
# ============================================================

if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        print("\n" + "=" * 60)
        print("Если в БД остались тестовые записи, почисти:")
        print()
        print("  PGPASSWORD=wspass2026 psql -U workspace_user -h localhost \\")
        print("    -d workspace_prod -c \\")
        print("    \"DELETE FROM project WHERE name LIKE 'CRUDTest_%';\"")
        print()
        print("  PGPASSWORD=wspass2026 psql -U workspace_user -h localhost \\")
        print("    -d workspace_prod -c \\")
        print("    \"DELETE FROM customer WHERE name LIKE 'CRUDTest_%';\"")
        print()
        print("  PGPASSWORD=wspass2026 psql -U workspace_user -h localhost \\")
        print("    -d workspace_prod -c \\")
        print("    \"DELETE FROM supplier WHERE name LIKE 'CRUDTest_%';\"")
        print("=" * 60)