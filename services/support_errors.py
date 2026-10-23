# services/support_errors.py
"""Хелпер для создания тикета поддержки при ошибке 500."""
import traceback


def create_error_ticket(url, method, user_info, traceback_text, flask_app=None):
    """Создаёт тикет в поддержке от имени системы.
    
    Возвращает ticket_id или None.
    """
    from extensions import db
    from models import User, SupportTicket, SupportMessage
    from utils import utcnow

    try:
        # 1. Находим системного пользователя
        system_user = User.query.filter_by(email='errors@workspace.local').first()
        if not system_user:
            print('⚠️ Системный пользователь errors@workspace.local не найден')
            return None

        # 2. Создаём тикет
        ticket = SupportTicket(
            user_id=system_user.id,
            subject=f'🚨 Ошибка 500: {url[:100]}',
            status='open',
            unread_for_admin=1,
            unread_for_user=0,
        )
        db.session.add(ticket)
        db.session.flush()  # чтобы получить ticket.id

        # 3. Формируем текст сообщения
        short_tb = (traceback_text or '')[-1500:]  # обрезаем до 1500 символов
        text = (
            f"Автоматическое сообщение об ошибке 500\n\n"
            f"URL: {url}\n"
            f"Метод: {method}\n"
            f"Пользователь: {user_info}\n\n"
            f"Traceback:\n{short_tb}"
        )

        msg = SupportMessage(
            ticket_id=ticket.id,
            author_id=system_user.id,
            role='user',
            text=text,
            is_read=False,
        )
        db.session.add(msg)
        db.session.commit()

        print(f'✅ Создан тикет поддержки #{ticket.id} об ошибке 500')
        return ticket.id

    except Exception as e:
        db.session.rollback()
        print(f'❌ Не удалось создать тикет об ошибке: {e}')
        return None