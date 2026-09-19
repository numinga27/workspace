#!/usr/bin/env python
"""
Скрипт для запуска по cron.
Проверяет дедлайны и отправляет уведомления исполнителям и руководителям.

Запуск: python cron_notifications.py
"""
from app import app, check_and_send_deadline_notifications

if __name__ == '__main__':
    with app.app_context():
        check_and_send_deadline_notifications()