"""Видеоконференции — PeerJS + WebRTC."""
import json
import secrets
from flask import Blueprint, redirect, url_for, flash, session, jsonify, request, render_template
from extensions import db, cache
from models import User, Notification, ConferenceInvite
from decorators import login_required

bp = Blueprint('video', __name__)

# Redis key prefix для видеоконференций
VIDEO_ROOM_KEY = 'video:room:'


def _get_room_peers(room_id):
    """Получить всех участников комнаты из Redis."""
    if not cache:
        return {}
    raw = cache.get(VIDEO_ROOM_KEY + room_id)
    if raw:
        return json.loads(raw)
    return {}


def _set_room_peer(room_id, user_id, peer_id):
    """Добавить/обновить участника в комнату."""
    if not cache:
        return
    peers = _get_room_peers(room_id)
    peers[str(user_id)] = peer_id
    # TTL 30 минут — автоматически очистит если браузер закрыт
    cache.set(VIDEO_ROOM_KEY + room_id, json.dumps(peers), timeout=1800)


def _remove_room_peer(room_id, user_id):
    """Удалить участника из комнаты."""
    if not cache:
        return
    peers = _get_room_peers(room_id)
    peers.pop(str(user_id), None)
    if peers:
        cache.set(VIDEO_ROOM_KEY + room_id, json.dumps(peers), timeout=1800)
    else:
        cache.delete(VIDEO_ROOM_KEY + room_id)


def _get_other_peers(room_id, current_user_id, current_peer_id):
    """Получить peer ID всех других участников."""
    peers = _get_room_peers(room_id)
    result = []
    for uid, pid in peers.items():
        if uid != str(current_user_id) and pid != current_peer_id:
            result.append({'user_id': int(uid), 'peer_id': pid})
    return result


# ============================================================
#  ПОИСК ПОЛЬЗОВАТЕЛЕЙ (autocomplete)
# ============================================================
@bp.route('/video/search-users')
@login_required
def search_users():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify({'users': []})
    
    current_user_id = session['user_id']
    
    users = User.query.filter(
        db.or_(
            User.first_name.ilike(f'%{q}%'),
            User.last_name.ilike(f'%{q}%'),
            User.username.ilike(f'%{q}%')
        ),
        User.id != current_user_id,
        User.is_active == True
    ).limit(10).all()
    
    return jsonify({
        'users': [
            {'id': u.id, 'name': f'{u.first_name} {u.last_name}', 'username': u.username}
            for u in users
        ]
    })


# ============================================================
#  ГЛАВНАЯ СТРАНИЦА КОНФЕРЕНЦИЙ
# ============================================================
@bp.route('/video/conference')
@login_required
def conference():
    user = User.query.get(session['user_id'])
    
    pending_invites = ConferenceInvite.query.filter_by(
        to_user_id=user.id,
        status='pending'
    ).order_by(ConferenceInvite.created_at.desc()).all()
    
    print(f'📹 User {user.id} has {len(pending_invites)} pending invites')
    for inv in pending_invites:
        print(f'   Invite id={inv.id}, from={inv.from_user_id}, room={inv.room_id}')
    
    # Ищем активное приглашение (accepted)
    current_invite = ConferenceInvite.query.filter(
        ConferenceInvite.status == 'accepted',
        db.or_(
            ConferenceInvite.from_user_id == user.id,
            ConferenceInvite.to_user_id == user.id
        )
    ).order_by(ConferenceInvite.created_at.desc()).first()
    
    room_id = current_invite.room_id if current_invite else None
    
    users_list = User.query.filter(
        User.id != user.id,
        User.is_active == True
    ).order_by(User.first_name, User.last_name).all()
    
    return render_template(
        'video_conference.html',
        user=user,
        pending_invites=pending_invites,
        room_id=room_id,
        unread_invite_count=len(pending_invites),
        users_list=users_list
    )


# ============================================================
#  СОЗДАТЬ КОМНАТУ
# ============================================================
@bp.route('/video/create-room', methods=['GET', 'POST'])
@login_required
def create_room():
    user = User.query.get(session['user_id'])
    room_id = 'room-' + secrets.token_hex(6)
    
    invite = ConferenceInvite(
        from_user_id=user.id,
        to_user_id=user.id,
        room_id=room_id,
        status='accepted'
    )
    db.session.add(invite)
    db.session.commit()
    
    if request.method == 'POST':
        return jsonify({'room_id': room_id})
    
    return redirect(url_for('video.conference') + f'#room-{room_id}')


# ============================================================
#  ОТПРАВИТЬ ПРИГЛАШЕНИЕ
# ============================================================
@bp.route('/video/invite', methods=['GET', 'POST'])
@login_required
def send_invite():
    if request.method == 'GET':
        return redirect(url_for('video.conference'))
    
    username = request.form.get('username', '').strip()
    if not username and request.is_json:
        json_data = request.get_json(silent=True)
        if json_data:
            username = json_data.get('username', '').strip()
    if not username:
        username = request.args.get('username', '').strip()
    
    if not username:
        flash('Ошибка: имя пользователя не получено', 'danger')
        return redirect(url_for('video.conference'))
    
    current_user = User.query.get(session['user_id'])
    
    parts = username.split()
    if len(parts) >= 2:
        target = User.query.filter(
            db.and_(
                User.first_name.ilike(f'{parts[0]}%'),
                User.last_name.ilike(f'{parts[1]}%')
            ),
            User.id != current_user.id,
            User.is_active == True
        ).first()
    else:
        target = User.query.filter(
            db.or_(
                User.first_name.ilike(f'%{username}%'),
                User.last_name.ilike(f'%{username}%')
            ),
            User.id != current_user.id,
            User.is_active == True
        ).first()
    
    if not target:
        flash(f'Пользователь "{username}" не найден в БД', 'danger')
        return redirect(url_for('video.conference'))
    
    # Проверка существующих приглашений
    existing = ConferenceInvite.query.filter_by(
        to_user_id=target.id,
        status='pending'
    ).first()
    
    if existing:
        print(f'⚠️ У {target.first_name} уже есть pending invite (id={existing.id}, room={existing.room_id})')
        flash(f'У {target.first_name} уже есть активное приглашение', 'warning')
        return redirect(url_for('video.conference'))
    
    # Используем ту же комнату, что у текущего пользователя (если есть)
    current_invite = ConferenceInvite.query.filter_by(
        from_user_id=current_user.id,
        status='accepted'
    ).first()
    
    if current_invite:
        room_id = current_invite.room_id
    else:
        room_id = 'room-' + secrets.token_hex(6)
    
    invite = ConferenceInvite(
        from_user_id=current_user.id,
        to_user_id=target.id,
        room_id=room_id,
        status='pending'
    )
    db.session.add(invite)
    
    notification = Notification(
        user_id=target.id,
        type='video_invite',
        title=f'📹 Видеозвонок от {current_user.first_name} {current_user.last_name}',
        body='Нажмите чтобы принять приглашение',
        url='/video/conference',
        from_user_id=current_user.id,
        is_read=False
    )
    db.session.add(notification)
    
    db.session.commit()
    
    try:
        from services.push import notify_new_video_invite
        from services.tasks import send_push_async
        push_data = notify_new_video_invite(target, current_user, room_id)
        if push_data:
            send_push_async.delay(**push_data)
    except Exception as e:
        print(f'⚠️ Ошибка push video invite: {e}')
    
    flash(f'✅ Приглашение отправлено {target.first_name} {target.last_name}', 'success')
    return redirect(url_for('video.conference'))


# ============================================================
#  МАССОВОЕ ПРИГЛАШЕНИЕ (несколько человек)
# ============================================================
@bp.route('/video/invite-batch', methods=['POST'])
@login_required
def invite_batch():
    data = request.get_json()
    usernames = data.get('usernames', [])
    
    if not usernames:
        return jsonify({'success': False, 'error': 'Нет пользователей'})
    
    current_user = User.query.get(session['user_id'])
    
    # Находим room_id текущего пользователя
    current_invite = ConferenceInvite.query.filter(
        ConferenceInvite.status == 'accepted',
        ConferenceInvite.from_user_id == current_user.id
    ).order_by(ConferenceInvite.created_at.desc()).first()
    
    if current_invite:
        room_id = current_invite.room_id
    else:
        room_id = 'room-' + secrets.token_hex(6)
    
    invited_count = 0
    errors = []
    
    for username in usernames:
        # Ищем пользователя
        parts = username.split()
        if len(parts) >= 2:
            target = User.query.filter(
                db.and_(
                    User.first_name.ilike(f'{parts[0]}%'),
                    User.last_name.ilike(f'{parts[1]}%')
                ),
                User.id != current_user.id,
                User.is_active == True
            ).first()
        else:
            target = User.query.filter(
                User.first_name.ilike(f'%{username}%'),
                User.id != current_user.id,
                User.is_active == True
            ).first()
        
        if not target:
            errors.append(username)
            continue
        
        # Проверка существующих pending приглашений
        existing = ConferenceInvite.query.filter_by(
            to_user_id=target.id,
            status='pending'
        ).first()
        
        if existing:
            errors.append(f'{username} (уже есть приглашение)')
            continue
        
        invite = ConferenceInvite(
            from_user_id=current_user.id,
            to_user_id=target.id,
            room_id=room_id,
            status='pending'
        )
        db.session.add(invite)
        
        notification = Notification(
            user_id=target.id,
            type='video_invite',
            title=f'📹 Видеозвонок от {current_user.first_name} {current_user.last_name}',
            body='Нажмите чтобы принять приглашение',
            url='/video/conference',
            from_user_id=current_user.id,
            is_read=False
        )
        db.session.add(notification)
        
        invited_count += 1
    
    db.session.commit()
    
    # Push уведомления
    if invited_count > 0:
        try:
            from services.push import notify_new_video_invite
            from services.tasks import send_push_async
            for username in usernames[:invited_count]:
                parts = username.split()
                target = User.query.filter(
                    db.and_(
                        User.first_name.ilike(f'{parts[0]}%'),
                        User.last_name.ilike(f'{parts[1]}%')
                    ),
                    User.id != current_user.id
                ).first()
                if target:
                    push_data = notify_new_video_invite(target, current_user, room_id)
                    if push_data:
                        send_push_async.delay(**push_data)
        except Exception as e:
            print(f'⚠️ Ошибка push batch: {e}')
    
    return jsonify({
        'success': True,
        'invited': invited_count,
        'errors': errors
    })


# ============================================================
#  ПРИНЯТЬ ПРИГЛАШЕНИЕ
# ============================================================
@bp.route('/video/accept/<int:invite_id>')
@login_required
def accept_invite(invite_id):
    invite = ConferenceInvite.query.get_or_404(invite_id)
    user = User.query.get(session['user_id'])
    
    if invite.to_user_id != user.id:
        flash('Это не ваше приглашение.', 'danger')
        return redirect(url_for('video.conference'))
    
    invite.status = 'accepted'
    
    # Обновляем оригинальный invite (от хоста к принявшему) в accepted
    original_invite = ConferenceInvite.query.filter_by(
        from_user_id=invite.from_user_id,
        to_user_id=invite.to_user_id,
        room_id=invite.room_id
    ).first()
    if original_invite:
        original_invite.status = 'accepted'
    
    notification = Notification(
        user_id=invite.from_user_id,
        type='video_invite',
        title=f'✅ {user.first_name} принял(а) приглашение на видеозвонок',
        body='Вы можете начать конференцию',
        url=url_for('video.conference', _external=False),
        from_user_id=user.id,
        is_read=False
    )
    db.session.add(notification)
    
    db.session.commit()
    
    return redirect(url_for('video.conference') + f'#room-{invite.room_id}')


# ============================================================
#  ПРЯМОЙ ДОСТУП ПО ССЫЛКЕ ИЗ УВЕДОМЛЕНИЯ
# ============================================================
@bp.route('/video/join/<int:invite_id>')
@login_required
def join_room(invite_id):
    invite = ConferenceInvite.query.get_or_404(invite_id)
    user = User.query.get(session['user_id'])
    
    if invite.to_user_id != user.id:
        flash('Это не ваше приглашение.', 'danger')
        return redirect(url_for('video.conference'))
    
    invite.status = 'accepted'
    
    # Обновляем оригинальный invite (от хоста к принявшему) в accepted
    original_invite = ConferenceInvite.query.filter_by(
        from_user_id=invite.from_user_id,
        to_user_id=invite.to_user_id,
        room_id=invite.room_id
    ).first()
    if original_invite:
        original_invite.status = 'accepted'
    
    notification = Notification(
        user_id=invite.from_user_id,
        type='video_invite',
        title=f'✅ {user.first_name} принял(а) видеозвонок',
        body='',
        url=url_for('video.conference', _external=False),
        from_user_id=user.id,
        is_read=False
    )
    db.session.add(notification)
    
    db.session.commit()
    
    return redirect(url_for('video.conference') + f'#room-{invite.room_id}')


# ============================================================
#  ОТКЛОНИТЬ ПРИГЛАШЕНИЕ
# ============================================================
@bp.route('/video/decline/<int:invite_id>', methods=['POST'])
@login_required
def decline_invite(invite_id):
    invite = ConferenceInvite.query.get_or_404(invite_id)
    user = User.query.get(session['user_id'])
    
    if invite.to_user_id != user.id:
        return jsonify({'error': 'Это не ваше приглашение'}), 403
    
    invite.status = 'declined'
    db.session.commit()
    
    return jsonify({'success': True})


# ============================================================
#  ПЕERJS СИГНАЛИЗАЦИЯ (Redis)
# ============================================================
@bp.route('/video/peer-signaling', methods=['POST'])
@login_required
def peer_signaling():
    data = request.json
    action = data.get('action')
    room_id = data.get('room_id')
    peer_id = data.get('peer_id')
    
    if not action or not room_id or not peer_id:
        return jsonify({'error': 'Missing params'}), 400
    
    user_id = session['user_id']
    
    if action == 'join':
        # Проверяем что пользователь в комнате
        room_invite = ConferenceInvite.query.filter_by(
            room_id=room_id,
            status='accepted'
        ).filter(
            db.or_(
                ConferenceInvite.from_user_id == user_id,
                ConferenceInvite.to_user_id == user_id
            )
        ).first()
        
        if not room_invite:
            return jsonify({'error': 'Not in room'}), 403
        
        # Регистрируем peer ID в Redis
        _set_room_peer(room_id, user_id, peer_id)
        
        # Получаем других участников
        other_peers = _get_other_peers(room_id, user_id, peer_id)
        
        print(f'📹 User {user_id} joined room {room_id}, peers: {other_peers}')
        
        return jsonify({'peers': other_peers})
    
    elif action == 'leave':
        # Удаляем peer ID из Redis
        _remove_room_peer(room_id, user_id)
        print(f'📹 User {user_id} left room {room_id}')
        return jsonify({'success': True})
    
    return jsonify({'error': 'Unknown action'}), 400


# ============================================================
#  ПОЛУЧИТЬ СПИСОК УЧАСТНИКОВ
# ============================================================
@bp.route('/video/participants/<room_id>')
@login_required
def get_participants(room_id):
    user = User.query.get(session['user_id'])
    
    invites = ConferenceInvite.query.filter_by(
        room_id=room_id,
        status='accepted'
    ).all()
    
    participants = []
    for inv in invites:
        u = User.query.get(inv.from_user_id if inv.from_user_id != user.id else inv.to_user_id)
        if u:
            participants.append({
                'id': u.id,
                'name': f'{u.first_name} {u.last_name}',
                'is_host': inv.from_user_id == user.id
            })
    
    return jsonify({'participants': participants})


# ============================================================
#  ЗАВЕРШИТЬ КОМНАТУ (для всех)
# ============================================================
@bp.route('/video/end-room/<room_id>', methods=['POST'])
@login_required
def end_room(room_id):
    user = User.query.get(session['user_id'])
    
    invites = ConferenceInvite.query.filter_by(
        room_id=room_id,
        status='accepted'
    ).all()
    
    for inv in invites:
        inv.status = 'ended'
        
        target = inv.from_user_id if inv.from_user_id != user.id else inv.to_user_id
        notification = Notification(
            user_id=target,
            type='video_invite',
            title=f'🔴 Конференция завершена',
            body=f'Видеоконференция {room_id} была завершена',
            url=url_for('video.conference', _external=False),
            from_user_id=user.id,
            is_read=False
        )
        db.session.add(notification)
    
    db.session.commit()
    
    return jsonify({'success': True})


# ============================================================
#  ВЫЙТИ ИЗ КОМНАТЫ (для одного пользователя)
# ============================================================
@bp.route('/video/leave-room/<room_id>', methods=['POST'])
@login_required
def leave_room(room_id):
    user = User.query.get(session['user_id'])
    
    user_invites = ConferenceInvite.query.filter(
        ConferenceInvite.room_id == room_id,
        ConferenceInvite.status == 'accepted',
        db.or_(
            ConferenceInvite.from_user_id == user.id,
            ConferenceInvite.to_user_id == user.id
        )
    ).all()
    
    for inv in user_invites:
        inv.status = 'left'
    
    db.session.commit()
    
    return jsonify({'success': True})


# ============================================================
#  ПОЛНЫЙ ВЫХОД ИЗ КОНФЕРЕНЦИИ (сброс комнаты)
# ============================================================
@bp.route('/video/leave-all', methods=['POST'])
@login_required
def leave_all():
    user = User.query.get(session['user_id'])
    
    # Находим все принятые приглашения пользователя
    user_invites = ConferenceInvite.query.filter(
        ConferenceInvite.status == 'accepted',
        db.or_(
            ConferenceInvite.from_user_id == user.id,
            ConferenceInvite.to_user_id == user.id
        )
    ).all()
    
    # Сбрасываем все приглашения
    for inv in user_invites:
        inv.status = 'left'
    
    db.session.commit()
    
    return jsonify({'success': True})
