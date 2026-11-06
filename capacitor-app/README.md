# Workspace App — Native Wrapper

Обёртка вашего веб-приложения в нативное приложение для Android и iOS через Capacitor.

## Структура

```
capacitor-app/
├── www/              # Ваш веб-сайт (копируется в нативные проекты)
├── src/              # Исходный JS для бейджа и push
├── android/          # Android проект (генерируется автоматически)
├── ios/              # iOS проект (генерируется автоматически)
├── capacitor.config.json  # Конфигурация Capacitor
└── package.json      # Зависимости
```

## Быстрый старт

### 1. Установите зависимости

```bash
cd capacitor-app
npm install
```

### 2. Настройте URL вашего сервера

Откройте `capacitor.config.json` и замените URL:

```json
{
  "server": {
    "url": "https://workspace.your-domain.com"
  }
}
```

Для локальной разработки:
```json
{
  "server": {
    "url": "http://localhost:8000"
  }
}
```

### 3. Запустите на Android

```bash
npx cap run android
```

Это откроет Android Studio и запустит приложение на эмуляторе или устройстве.

### 4. Запустите на iOS (нужен Mac)

```bash
npx cap run ios
```

## Бейдж на иконке

Бейдж автоматически обновляется из вашего Flask-приложения.

### На бэкенде (Flask)

Добавьте endpoint для получения счётчика непрочитанных:

```python
@bp.route('/api/v1/unread-count')
@token_required
def api_unread_count():
    user_id = session.get('user_id')
    
    # Непрочитанные сообщения
    chat_unread = db.session.query(func.count(Message.id)).filter(
        Message.user_id != user_id,
        ~MessageRead.message_id.in_(
            db.session.query(MessageRead.message_id).filter_by(user_id=user_id)
        )
    ).scalar() or 0
    
    # Непрочитанные упоминания
    mentions_unread = MessageMention.query.filter_by(
        user_id=user_id, is_read=False
    ).count()
    
    return jsonify({
        'chat': chat_unread,
        'mentions': mentions_unread,
        'total': chat_unread + mentions_unread,
    })
```

### На фронтенде (отправка бейджа)

Когда пользователь открывает приложение, отправляет сообщение или получает push — обновите localStorage:

```javascript
localStorage.setItem('workspace_unread', '5');
```

Обёртка автоматически синхронизирует это с нативным бейджем каждые 5 секунд.

## Push-уведомления

### На бэкенде

Когда отправляете push через Firebase, убедитесь что payload содержит:

```python
push_data = {
    'title': '💬 Иван ответил вам',
    'body': 'Проект Стройка\nДа, завтра привезём',
    'data': {
        'url': '/project/123#chat',
    },
}
```

### На фронтенде

Push обрабатывается в `src/index.js`. При получении push:
- Увеличивается бейдж
- Вибрация (haptics)
- Токен отправляется на сервер

## Сборка APK / IPA

### Android (APK)

```bash
cd android
./gradlew assembleRelease
```

APK будет в `android/app/build/outputs/apk/release/`

### iOS (IPA)

Откройте `ios/App/App.xcworkspace` в Xcode и нажмите Archive.

## Решения проблем

### Плагин бейджа не работает

Убедитесь что `@capawesome/capacitor-badge` установлен:
```bash
npm list @capawesome/capacitor-badge
```

### Push не работает

1. Для Android нужен Google Play Services
2. Для iOS нужен provisioning profile с Push Notifications entitlement
3. Проверьте VAPID ключи в `config.py`

### Приложение не загружается

Проверьте URL в `capacitor.config.json`. Для HTTPS нужен SSL-сертификат.
