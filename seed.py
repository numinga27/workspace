"""
Скрипт наполнения БД тестовыми данными.
Запуск: python seed.py
"""
from app import (app, db, User, Customer, Project, ProjectMember, Milestone,
                 Task, Todo, Report, Message, Event)
from datetime import datetime, timedelta

with app.app_context():
    print("🌱 Начинаем наполнение базы данных...")

    # ============================================================
    # 1. ПОЛЬЗОВАТЕЛИ
    # ============================================================
    def get_or_create_user(first_name, last_name, email, role, company='ООО СтройИнвест', password='123456'):
        user = User.query.filter_by(email=email).first()
        if user:
            return user
        user = User(
            first_name=first_name,
            last_name=last_name,
            company=company,
            email=email,
            password=password,
            role=role
        )
        db.session.add(user)
        db.session.commit()
        print(f"  + Пользователь: {first_name} {last_name} ({email})")
        return user

    admin = get_or_create_user('Иван', 'Петров', 'admin@example.com', 'admin', 'ООО Рога и Копыта', 'admin123')
    chief = get_or_create_user('Сергей', 'Иванов', 'chief@example.com', 'user')
    logistic = get_or_create_user('Анна', 'Смирнова', 'logistic@example.com', 'user')
    manager = get_or_create_user('Дмитрий', 'Козлов', 'manager@example.com', 'user')
    worker1 = get_or_create_user('Михаил', 'Соколов', 'worker1@example.com', 'user')
    worker2 = get_or_create_user('Елена', 'Новикова', 'worker2@example.com', 'user')

    # ============================================================
    # 2. ЗАКАЗЧИКИ
    # ============================================================
    def get_or_create_customer(name, inn, contact_person, phone, email, address):
        c = Customer.query.filter_by(inn=inn).first()
        if c:
            return c
        c = Customer(
            name=name, inn=inn, contact_person=contact_person,
            phone=phone, email=email, address=address
        )
        db.session.add(c)
        db.session.commit()
        print(f"  + Заказчик: {name}")
        return c

    customer1 = get_or_create_customer(
        'ПАО "ГазпромНефть"', '7708123456', 'Алексей Тихонов',
        '+7 (495) 123-45-67', 'a.tihonov@gazprom.ru',
        'г. Москва, ул. Ленина, д. 15'
    )
    customer2 = get_or_create_customer(
        'ООО "ТехноПарк"', '7801234567', 'Мария Сидорова',
        '+7 (812) 987-65-43', 'm.sidorova@technopark.ru',
        'г. Санкт-Петербург, пр. Невский, д. 88'
    )
    customer3 = get_or_create_customer(
        'АО "Мегастрой"', '5023456789', 'Владимир Орлов',
        '+7 (499) 555-77-88', 'v.orlov@megastroy.ru',
        'г. Москва, ул. Строителей, д. 3'
    )

    # ============================================================
    # 3. ПРОЕКТЫ
    # ============================================================
    def create_project_if_not_exists(name, description, customer, members_roles, status='active',
                                     start_offset_days=-30, end_offset_days=60):
        existing = Project.query.filter_by(name=name).first()
        if existing:
            print(f"  ~ Проект уже существует: {name}")
            return existing

        now = datetime.utcnow()
        project = Project(
            name=name,
            description=description,
            created_by=admin.id,
            customer_id=customer.id,
            start_date=now + timedelta(days=start_offset_days),
            end_date=now + timedelta(days=end_offset_days),
            status=status
        )
        db.session.add(project)
        db.session.commit()
        print(f"  + Проект: {name}")

        for user, role in members_roles:
            if not ProjectMember.query.filter_by(user_id=user.id, project_id=project.id).first():
                db.session.add(ProjectMember(
                    user_id=user.id,
                    project_id=project.id,
                    role_in_project=role
                ))
        db.session.commit()
        return project

    # ---- ПРОЕКТ 1: ЖК "Северный" ----
    p1 = create_project_if_not_exists(
        'ЖК "Северный" — строительство корпуса А',
        'Строительство 17-этажного жилого корпуса с подземным паркингом.',
        customer1,
        [
            (admin, 'admin'),
            (chief, 'chief_engineer'),
            (logistic, 'logistic'),
            (manager, 'manager'),
            (worker1, 'member'),
            (worker2, 'member'),
        ],
        status='active',
        start_offset_days=-60,
        end_offset_days=180
    )

    # ---- ПРОЕКТ 2: Реконструкция офиса ----
    p2 = create_project_if_not_exists(
        'Реконструкция офиса "ТехноПарк"',
        'Капитальный ремонт офисного центра: замена инженерных систем, отделка.',
        customer2,
        [
            (admin, 'admin'),
            (manager, 'manager'),
            (worker1, 'member'),
        ],
        status='active',
        start_offset_days=-15,
        end_offset_days=45
    )

    # ---- ПРОЕКТ 3: Склад (завершён) ----
    p3 = create_project_if_not_exists(
        'Строительство склада "Мегастрой"',
        'Строительство логистического склада площадью 5000 кв.м.',
        customer3,
        [
            (admin, 'admin'),
            (chief, 'chief_engineer'),
            (logistic, 'logistic'),
        ],
        status='completed',
        start_offset_days=-180,
        end_offset_days=-10
    )

    # ============================================================
    # 4. ВЕХИ
    # ============================================================
    def add_milestone(project, name, desc, order_idx, due_offset_days, is_completed=False):
        existing = Milestone.query.filter_by(project_id=project.id, name=name).first()
        if existing:
            return existing
        m = Milestone(
            name=name, description=desc, project_id=project.id,
            order_index=order_idx,
            due_date=datetime.utcnow() + timedelta(days=due_offset_days),
            is_completed=is_completed,
            completed_at=datetime.utcnow() if is_completed else None,
            created_by=admin.id
        )
        db.session.add(m)
        db.session.commit()
        return m

    # Вехи проекта 1 (часть просрочена)
    m1 = add_milestone(p1, 'Проектная документация', 'Согласование проекта', 0, -40, True)
    m2 = add_milestone(p1, 'Фундамент', 'Заливка фундамента и гидроизоляция', 1, -20, True)
    m3 = add_milestone(p1, 'Каркас здания', 'Возведение монолитного каркаса', 2, -5, False)  # ПРОСРОЧЕНА
    m4 = add_milestone(p1, 'Кровля', 'Монтаж кровли и водостоков', 3, 30, False)
    m5 = add_milestone(p1, 'Фасад', 'Отделка фасада и остекление', 4, 60, False)
    m6 = add_milestone(p1, 'Инженерные системы', 'Водоснабжение, электрика, вентиляция', 5, 90, False)
    m7 = add_milestone(p1, 'Благоустройство', 'Двор, парковка, озеленение', 6, 150, False)

    # Вехи проекта 2
    add_milestone(p2, 'Демонтаж', 'Снос старых конструкций', 0, -10, True)
    add_milestone(p2, 'Инженерные системы', 'Замена труб, проводки', 1, 10, False)
    add_milestone(p2, 'Отделочные работы', 'Штукатурка, покраска', 2, 30, False)
    add_milestone(p2, 'Финальная сдача', 'Приёмка и уборка', 3, 45, False)

    # Вехи проекта 3
    add_milestone(p3, 'Фундамент', 'Готово', 0, -150, True)
    add_milestone(p3, 'Каркас', 'Готово', 1, -100, True)
    add_milestone(p3, 'Кровля', 'Готово', 2, -50, True)
    add_milestone(p3, 'Сдача объекта', 'Готово', 3, -15, True)

    # ============================================================
    # 5. ЗАДАЧИ
    # ============================================================
    def add_task(project, title, desc, assigned_to, status='new', due_offset_days=15,
                 milestone=None, parent_task=None):
        existing = Task.query.filter_by(project_id=project.id, title=title).first()
        if existing:
            return existing
        t = Task(
            title=title, description=desc,
            project_id=project.id,
            assigned_to=assigned_to.id if assigned_to else None,
            created_by=admin.id,
            status=status,
            due_date=datetime.utcnow() + timedelta(days=due_offset_days),
            milestone_id=milestone.id if milestone else None,
            parent_task_id=parent_task.id if parent_task else None,
        )
        db.session.add(t)
        db.session.commit()
        return t

    # Задачи проекта 1
    t1 = add_task(p1, 'Заказать арматуру', 'Арматура А500С 12мм — 20 тонн',
                  logistic, 'completed', -30, m2)
    t2 = add_task(p1, 'Проверить качество бетона', 'Лабораторный анализ образцов',
                  chief, 'completed', -25, m2)
    t3 = add_task(p1, 'Возведение 5 этажа', 'Монолитные работы 5-го этажа',
                  worker1, 'in_progress', -3, m3)  # ПРОСРОЧЕНА
    t4 = add_task(p1, 'Возведение 6 этажа', 'Монолитные работы 6-го этажа',
                  worker1, 'new', 7, m3)
    t5 = add_task(p1, 'Возведение 7-9 этажей', 'Монолитные работы',
                  worker2, 'new', 20, m3)
    t6 = add_task(p1, 'Заказать профнастил', 'Профнастил для кровли 3000 м²',
                  logistic, 'new', 25, m4)
    t7 = add_task(p1, 'Монтаж вентиляции', 'Проектирование и монтаж',
                  chief, 'new', 80, m6)

    # Подзадачи t3
    add_task(p1, 'Установить опалубку 5 этаж', 'Опалубочные работы',
             worker1, 'completed', -10, m3, parent_task=t3)
    add_task(p1, 'Армирование 5 этаж', 'Вязка арматуры',
             worker2, 'completed', -7, m3, parent_task=t3)
    add_task(p1, 'Заливка бетона 5 этаж', 'Бетонирование',
             worker1, 'in_progress', -2, m3, parent_task=t3)

    # Задачи проекта 2
    add_task(p2, 'Демонтаж перегородок', 'Снос старых стен',
             worker1, 'completed', -8)
    add_task(p2, 'Замена труб', 'Монтаж новых труб ХВС/ГВС',
             chief, 'in_progress', 5)
    add_task(p2, 'Установка кондиционеров', 'Монтаж сплит-систем',
             manager, 'new', 20)
    add_task(p2, 'Покраска стен', 'Финишная отделка',
             worker1, 'new', 28)

    # Задачи проекта 3
    add_task(p3, 'Фундаментные работы', 'Готово', chief, 'completed', -140)
    add_task(p3, 'Возведение каркаса', 'Готово', worker1, 'completed', -90)
    add_task(p3, 'Кровельные работы', 'Готово', worker2, 'completed', -40)

    # ============================================================
    # 6. TO-DO
    # ============================================================
    def add_todo(project, title, assigned_to, is_done=False):
        existing = Todo.query.filter_by(project_id=project.id, title=title).first()
        if existing:
            return existing
        t = Todo(
            title=title,
            project_id=project.id,
            assigned_to=assigned_to.id if assigned_to else None,
            created_by=admin.id,
            is_done=is_done,
            done_at=datetime.utcnow() if is_done else None
        )
        db.session.add(t)
        db.session.commit()
        return t

    add_todo(p1, 'Согласовать смету с заказчиком', admin, False)
    add_todo(p1, 'Заказать геодезическую съёмку', chief, True)
    add_todo(p1, 'Проверить аптечку на объекте', manager, False)
    add_todo(p1, 'Закупить спецодежду для бригады', logistic, False)
    add_todo(p1, 'Оформить пропуска на объект', manager, True)

    add_todo(p2, 'Согласовать дизайн-проект', manager, True)
    add_todo(p2, 'Заказать материалы для отделки', logistic, False)
    add_todo(p2, 'Проверить вентиляцию', chief, False)

    # ============================================================
    # 7. ОТЧЁТЫ
    # ============================================================
    def add_report(project, title, content, author, milestone=None,
                   reason='on_track', reason_detail='', delay_days=0, days_ago=1):
        r = Report(
            title=title, content=content,
            project_id=project.id,
            milestone_id=milestone.id if milestone else None,
            author_id=author.id,
            reason=reason,
            reason_detail=reason_detail,
            delay_days=delay_days,
            created_at=datetime.utcnow() - timedelta(days=days_ago)
        )
        db.session.add(r)
        db.session.commit()

    add_report(p1, 'Отчёт за неделю 1',
               'Завершены работы по фундаменту. Начаты работы по возведению каркаса.',
               manager, m2, 'on_track', '', 0, 30)
    add_report(p1, 'Проблема с поставкой арматуры',
               'Поставщик задержал поставку на 3 дня из-за логистических проблем.',
               logistic, m3, 'delay_supply', 'Поставщик ООО "МеталлТорг" задержал поставку', 3, 15)
    add_report(p1, 'Отставание по каркасу',
               'Отставание от графика на 5 дней. Связано с задержкой поставки арматуры.',
               chief, m3, 'delay_supply', 'Задержка арматуры повлияла на сроки', 5, 3)
    add_report(p2, 'Старт реконструкции',
               'Демонтажные работы выполнены в срок. Начинаем замену инженерных систем.',
               manager, None, 'on_track', '', 0, 5)

    # ============================================================
    # 8. СООБЩЕНИЯ
    # ============================================================
    def add_message(project, user, text, hours_ago=1):
        m = Message(
            text=text,
            user_id=user.id,
            project_id=project.id,
            created_at=datetime.utcnow() - timedelta(hours=hours_ago)
        )
        db.session.add(m)
        db.session.commit()

    add_message(p1, admin, 'Всем привет! Начинаем работу над корпусом А.', 72)
    add_message(p1, chief, 'Фундамент готов, начинаем армирование.', 48)
    add_message(p1, worker1, 'Опалубка на 5 этаже установлена.', 24)
    add_message(p1, manager, 'Коллеги, заказчик просил ускориться с каркасом.', 12)
    add_message(p1, logistic, 'Арматура придёт в пятницу.', 6)
    add_message(p1, chief, 'Хорошо, работаем по графику.', 2)

    add_message(p2, manager, 'Реконструкция стартовала.', 96)
    add_message(p2, worker1, 'Демонтаж почти закончен.', 48)
    add_message(p2, chief, 'Замена труб начнётся со следующей недели.', 12)

    # ============================================================
    # 9. СОБЫТИЯ В КАЛЕНДАРЕ
    # ============================================================
    def add_event(project, title, description, creator, days_from_now, hour=10,
                  duration_hours=1, all_day=False, color='blue'):
        existing = Event.query.filter_by(project_id=project.id, title=title).first()
        if existing:
            return existing

        if all_day:
            start = (datetime.utcnow() + timedelta(days=days_from_now)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            end = None
        else:
            start = (datetime.utcnow() + timedelta(days=days_from_now)).replace(
                hour=hour, minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=duration_hours)

        e = Event(
            title=title,
            description=description,
            start_time=start,
            end_time=end,
            all_day=all_day,
            color=color,
            project_id=project.id,
            created_by=creator.id
        )
        db.session.add(e)
        db.session.commit()
        print(f"  + Событие: {title} ({start.strftime('%d.%m.%Y %H:%M')})")
        return e

    # События проекта 1 (ЖК "Северный")
    add_event(p1, 'Планёрка по проекту',
              'Еженедельная планёрка: обсуждение текущего прогресса',
              admin, days_from_now=1, hour=10, duration_hours=1, color='blue')

    add_event(p1, 'Встреча с заказчиком',
              'Обсуждение сроков и хода строительства с ПАО "ГазпромНефть"',
              admin, days_from_now=3, hour=14, duration_hours=2, color='purple')

    add_event(p1, 'Осмотр фундамента',
              'Приёмка работ по фундаменту с участием главного инженера',
              chief, days_from_now=7, hour=9, duration_hours=3, color='green')

    add_event(p1, 'Совещание по каркасу',
              'Обсуждение отставания от графика и мер по ускорению',
              manager, days_from_now=2, hour=15, duration_hours=1, color='orange')

    add_event(p1, 'Проверка техники безопасности',
              'Плановый осмотр объекта на соответствие нормам ТБ',
              manager, days_from_now=10, hour=11, duration_hours=2, color='red')

    add_event(p1, 'День рождения Сергея Иванова',
              'Поздравляем главного инженера! 🎉',
              admin, days_from_now=5, all_day=True, color='orange')

    add_event(p1, 'Сдача 5 этажа',
              'Приёмка монолитных работ 5-го этажа',
              chief, days_from_now=14, hour=10, duration_hours=4, color='teal')

    # События проекта 2 (Реконструкция офиса)
    add_event(p2, 'Старт замены труб',
              'Начало работ по замене инженерных систем',
              manager, days_from_now=1, hour=9, duration_hours=8, color='blue')

    add_event(p2, 'Осмотр вентиляции',
              'Проверка текущего состояния вентиляционной системы',
              chief, days_from_now=4, hour=13, duration_hours=2, color='green')

    add_event(p2, 'Согласование дизайна',
              'Презентация дизайн-проекта заказчику',
              manager, days_from_now=6, hour=16, duration_hours=1, color='purple')

    # События проекта 3 (Склад — завершён)
    add_event(p3, 'Годовщина сдачи объекта',
              'Год с момента сдачи склада в эксплуатацию',
              admin, days_from_now=20, all_day=True, color='green')

    # ============================================================
    # ИТОГО
    # ============================================================
    print("")
    print("✅ Готово! Создано:")
    print(f"   - Пользователей: {User.query.count()}")
    print(f"   - Заказчиков: {Customer.query.count()}")
    print(f"   - Проектов: {Project.query.count()}")
    print(f"   - Вех: {Milestone.query.count()}")
    print(f"   - Задач: {Task.query.count()}")
    print(f"   - To-Do: {Todo.query.count()}")
    print(f"   - Отчётов: {Report.query.count()}")
    print(f"   - Сообщений: {Message.query.count()}")
    print(f"   - Событий: {Event.query.count()}")
    print("")
    print("📋 Тестовые аккаунты:")
    print("   admin@example.com     / admin123  — Администратор (глобальный)")
    print("   chief@example.com     / 123456    — Главный инженер")
    print("   logistic@example.com  / 123456    — Логистик")
    print("   manager@example.com   / 123456    — Менеджер")
    print("   worker1@example.com   / 123456    — Рабочий")
    print("   worker2@example.com   / 123456    — Рабочий")
    print("")
    print("📅 События в календаре:")
    print("   Проект 1 (ЖК Северный): 7 событий — планёрка, встреча с заказчиком,")
    print("     осмотр фундамента, совещание по каркасу, проверка ТБ,")
    print("     день рождения, сдача 5 этажа")
    print("   Проект 2 (Реконструкция): 3 события — старт замены труб,")
    print("     осмотр вентиляции, согласование дизайна")
    print("   Проект 3 (Склад): 1 событие — годовщина сдачи")