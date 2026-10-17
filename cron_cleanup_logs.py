#!/usr/bin/env python
"""Cron: удаляет записи ActivityLog старше 30 дней."""
from app import create_app
from services.audit import cleanup_old_logs

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        count = cleanup_old_logs(days=30)
        print(f'Удалено старых записей: {count}')