from . import auth
from . import dashboard
from . import tasks
from . import projects
from . import todos
from . import reports
from . import files
from . import chat
from . import calendar
from . import customers
from . import suppliers          # ← НОВОЕ
from . import contacts           # ← НОВОЕ
from . import team
from . import pdf
from . import admin
from . import users_admin 
from . import companies  


ALL_BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    tasks.bp,
    projects.bp,
    todos.bp,
    reports.bp,
    files.bp,
    chat.bp,
    calendar.bp,
    customers.bp,
    suppliers.bp,                # ← НОВОЕ
    contacts.bp,                 # ← НОВОЕ
    team.bp,
    pdf.bp,
    admin.bp,
    users_admin.bp,
    companies.bp,
]


def register_blueprints(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)