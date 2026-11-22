"""Сигнальный сервер для видеозвонков на Flask-SocketIO."""
from flask import Blueprint, session, request
from flask_socketio import emit, join_room
from extensions import db
from models import ConferenceInvite

bp = Blueprint('video_ws', __name__)

# Хранилище участников в памяти: {room_id: {user_id: {peer_id, sid}}}
rooms = {}

# Очередь SDP для пользователей которые ещё не в комнате: {user_id: [sdp_data, ...]}
sdp_queue = {}


def init_video_socketio(sio):
    """Вызвать из app.py после создания SocketIO."""
    import sys
    print(f'🔌 SocketIO инициализирован: {sio}', flush=True)
    sys.stdout.flush()
    
    @sio.on('join_conference')
    def handle_join_conference(data):
        """Пользователь заходит в видеозвонок."""
        room_id = data.get('room_id')
        peer_id = data.get('peer_id')
        user_id = session.get('user_id')
        sid = request.sid
        
        print(f'📥 join_conference: room={room_id}, peer={peer_id}, user={user_id}, sid={sid}', flush=True)
        sys.stdout.flush()
        
        if not room_id or not peer_id:
            return
        
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
            emit('error', {'message': 'Not in room'})
            return
        
        # Присоединяемся к сокет-комнате
        join_room(room_id)
        
        # Запоминаем участника
        if room_id not in rooms:
            rooms[room_id] = {}
        rooms[room_id][user_id] = {'peer_id': peer_id, 'sid': sid}
        
        print(f'📹 User {user_id} joined room {room_id}, peer={peer_id}, sid={sid}', flush=True)
        sys.stdout.flush()
        
        # Получаем список всех участников комнаты
        room_users = rooms.get(room_id, {})
        peers = [{'user_id': uid, 'peer_id': info['peer_id']} for uid, info in room_users.items()]
        
        # ОТСЫЛАЕМ новому участнику список всех peer_id
        emit('peer_list', {'peers': peers}, to=sid)
        
        # ОСТАЛЬНЫМ участникам отправляем уведомление о новом
        emit('user_joined', {
            'peer_id': peer_id,
            'user_id': user_id
        }, room=room_id, include_self=False)
        
        # Отправляем все queued SDP этому пользователю
        if user_id in sdp_queue:
            queued_sdps = sdp_queue.pop(user_id)
            print(f'📥 Отправляем {len(queued_sdps)} queued SDP пользователю {user_id}', flush=True)
            for queued in queued_sdps:
                emit('receive_sdp', {
                    'sdp': queued['sdp'],
                    'from_peer_id': queued['from_peer_id'],
                    'from_user_id': queued['from_user_id']
                }, room=sid)
    
    @sio.on('send_sdp')
    def handle_send_sdp(data):
        """Передача SDP offer/answer."""
        target_user_id = data.get('target_user_id')
        sdp = data.get('sdp')
        peer_id = data.get('peer_id')
        user_id = session.get('user_id')
        
        print(f'📤 send_sdp: target={target_user_id}, from={user_id}', flush=True)
        
        # Ищем комнату, где есть target_user_id
        found = False
        for room_id, users in rooms.items():
            if target_user_id in users:
                target_sid = users[target_user_id]['sid']
                emit('receive_sdp', {
                    'sdp': sdp,
                    'from_peer_id': peer_id,
                    'from_user_id': user_id
                }, room=target_sid)
                print(f'📤 SDP отправлен пользователю {target_user_id}', flush=True)
                found = True
                break
        
        if not found:
            print(f'⏳ target_user_id {target_user_id} не в комнате — сохраняем в очередь', flush=True)
            if target_user_id not in sdp_queue:
                sdp_queue[target_user_id] = []
            sdp_queue[target_user_id].append({
                'sdp': sdp,
                'from_peer_id': peer_id,
                'from_user_id': user_id
            })
    
    @sio.on('send_ice')
    def handle_send_ice(data):
        """Передача ICE кандидата."""
        target_user_id = data.get('target_user_id')
        ice_candidate = data.get('ice_candidate')
        
        # Ищем комнату, где есть target_user_id
        for room_id, users in rooms.items():
            if target_user_id in users:
                target_sid = users[target_user_id]['sid']
                emit('receive_ice', {
                    'candidate': ice_candidate,
                    'from_peer_id': data.get('peer_id')
                }, room=target_sid)
                print(f'📤 ICE отправлен пользователю {target_user_id}', flush=True)
                break
    
    @sio.on('leave_conference')
    def handle_leave_conference(data):
        """Пользователь выходит из звонка."""
        room_id = data.get('room_id')
        peer_id = data.get('peer_id')
        user_id = session.get('user_id')
        
        leave_room(room_id)
        
        if room_id in rooms and user_id in rooms[room_id]:
            del rooms[room_id][user_id]
            if not rooms[room_id]:
                del rooms[room_id]
        
        print(f'📹 User {user_id} left room {room_id}')
        
        emit('user_left', {
            'peer_id': peer_id,
            'user_id': user_id
        }, room=room_id, include_self=False)
    
    @sio.on('disconnect')
    def handle_disconnect():
        """Пользователь закрыл браузер."""
        print('📹 Client disconnected')
