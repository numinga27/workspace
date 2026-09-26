#!/usr/bin/env python
from app import create_app
from services.email import check_and_send_deadline_notifications

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        check_and_send_deadline_notifications()
