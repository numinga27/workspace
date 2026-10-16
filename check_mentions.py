#!/usr/bin/env python
"""
Проверка системы упоминаний.
Запуск: cd ~/workspace && source venv/bin/activate && python check_mentions.py
"""
from app import create_app
from models import MessageMention, Message, User, Project
from utils import get_project_mentionable_users, parse_mentions_in_text

app = create_app()

with app.app_context():
    print('\n' + '=' * 80)
    print('УПОМИНАНИЯ В БД')
    print('=' * 80)

    total = MessageMention.query.count()
    unread = MessageMention.query.filter_by(is_read=False).count()
    print(f'Всего: {total}, непрочитанных: {unread}')

    if total > 0:
        print('\nПоследние 10:')
        for m in MessageMention.query.order_by(MessageMention.created_at.desc()).limit(10):
            author = m.message.author if m.message else None
            author_name = author.full_name if author else '?'
            project = m.project.name if m.project else '?'
            status = '🔵 новое' if not m.is_read else '✓ прочитано'
            print(f'  [{m.id}] {project}: {author_name} → {m.user.full_name} ({status})')
            print(f'      "{m.message.text[:80] if m.message else "(удалено)"}"')

    print('\n' + '=' * 80)
    print('ТЕСТ ПАРСИНГА @')
    print('=' * 80)

    # Возьми первый проект, где есть участники
    projects = Project.query.limit(5).all()
    for project in projects:
        users = get_project_mentionable_users(project.id)
        if not users:
            continue

        print(f'\nПроект: {project.name} (ID={project.id})')
        print(f'Участников для упоминания: {len(users)}')
        for u, member in users[:5]:
            print(f'  ID={u.id} | {u.first_name} {u.last_name} | {member.role_display}')

        # Тест 1: точное упоминание первого участника
        user, member = users[0]
        test_text = f'@{user.first_name} {user.last_name} тестовое сообщение'
        found = parse_mentions_in_text(test_text, project.id)
        print(f'\n  Тест 1: "{test_text}"')
        print(f'  Найдено: {found}')
        if user.id in found:
            print(f'  ✅ Работает!')
        else:
            print(f'  ❌ Не находит упоминание своего же имени!')

        # Тест 2: несуществующее имя
        test_text2 = '@Несуществующее Имя привет'
        found2 = parse_mentions_in_text(test_text2, project.id)
        print(f'\n  Тест 2: "{test_text2}"')
        print(f'  Найдено: {found2}')
        if not found2:
            print(f'  ✅ Правильно (не находит)')
        else:
            print(f'  ⚠️ Неожиданно нашёл: {found2}')

    print('\n' + '=' * 80)
    print('ГОТОВО')
    print('=' * 80 + '\n')