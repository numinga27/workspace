// ============================================================
//  VIDEO CONFERENCE - WebRTC + SocketIO (без PeerJS)
// ============================================================

let peerConnection = null;
let localStream = null;
let socket = null;
let currentRoom = null;
let currentPeerId = null;
let myUserId = null;
let remotePeerId = null;
let isInCall = false;

async function initPeerJS(roomId) {
    currentRoom = roomId;
    console.log('🚀 Инициализация видеосвязи для комнаты:', roomId);
    console.log('👤 USER_ID:', USER_ID);
    console.log('📱 navigator.mediaDevices:', typeof navigator.mediaDevices);
    
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.error('❌ getUserMedia не поддерживается!');
        var videoGrid = document.getElementById('videoGrid');
        if (videoGrid) {
            var errDiv = document.createElement('div');
            errDiv.className = 'alert alert-danger m-3';
            errDiv.innerHTML = '<i class="bi bi-exclamation-triangle"></i> ' +
                'Ваш браузер не поддерживает WebRTC. ' +
                'Используйте Chrome, Firefox или Safari.';
            videoGrid.appendChild(errDiv);
        }
        return;
    }
    
    try {
        // 1. Сначала подключаемся к SocketIO
        console.log('🔌 Подключение к SocketIO...');
        const io = window.io;
        socket = io(window.location.origin, {
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionAttempts: 10
        });
        
        socket.on('connect', function() {
            console.log('✅ SocketIO подключён');
            
            // 2. Генерируем уникальный ID
            currentPeerId = 'user-' + USER_ID + '-' + Date.now();
            myUserId = USER_ID;
            console.log('🆔 Мой peer_id:', currentPeerId);
            
            // 3. Сообщаем серверу о входе в комнату
            console.log('📥 Join room:', roomId);
            socket.emit('join_conference', {
                room_id: roomId,
                peer_id: currentPeerId,
                user_id: USER_ID
            });
        });
        
        socket.on('user_joined', function(data) {
            console.log('👤 Новый участник:', data);
            remotePeerId = data.peer_id;
            requestMediaAndCall(data.peer_id, data.user_id);
        });
        
        socket.on('peer_list', function(data) {
            console.log('👥 Список участников:', data.peers);
            // Начинаем звонок с каждым участником (кроме себя)
            data.peers.forEach(function(peerInfo) {
                if (peerInfo.peer_id !== currentPeerId) {
                    console.log('📞 Начинаю звонок к:', peerInfo.peer_id, 'user_id:', peerInfo.user_id);
                    requestMediaAndCall(peerInfo.peer_id, peerInfo.user_id);
                }
            });
        });
        
        socket.on('receive_sdp', function(data) {
            console.log('📥 Получен SDP от:', data.from_peer_id);
            handleSDP(data.sdp, data.from_peer_id, data.from_user_id);
        });
        
        socket.on('receive_ice', function(data) {
            console.log('🧊 Получен ICE кандидат');
            handleICE(data.candidate, data.from_peer_id);
        });
        
        socket.on('user_left', function(data) {
            console.log('👋 Участник вышел:', data);
            removeRemoteVideo(data.peer_id);
        });
        
        socket.on('error', function(err) {
            console.error('❌ SocketIO ошибка:', err);
        });
        
        socket.on('disconnect', function() {
            console.warn('⚠️ SocketIO отключён');
        });
        
        // 4. Запрашиваем доступ к камере/микрофону (после подключения к SocketIO)
        console.log('📹 Запрос доступа к камере/микрофону...');
        try {
            localStream = await navigator.mediaDevices.getUserMedia({
                video: true,
                audio: true
            });
            console.log('✅ Доступ к камере получен');
            
            // Показываем локальное видео
            const localVideo = document.getElementById('localVideo');
            if (localVideo) {
                localVideo.srcObject = localStream;
            }
        } catch (mediaErr) {
            console.error('❌ Ошибка доступа к медиа:', mediaErr);
            var videoGrid = document.getElementById('videoGrid');
            if (videoGrid) {
                var errDiv = document.createElement('div');
                errDiv.className = 'alert alert-danger m-3';
                errDiv.innerHTML = '<i class="bi bi-exclamation-triangle"></i> ' +
                    'Не удалось получить доступ к камере/микрофону. ' +
                    'Проверьте разрешения в браузере.' +
                    '<br><a href="/video/conference" class="btn btn-sm btn-warning mt-2">' +
                    '<i class="bi bi-box-arrow-right"></i> Выйти из комнаты</a>';
                videoGrid.appendChild(errDiv);
            }
            return;
        }
        
    } catch (err) {
        console.error('❌ Ошибка инициализации:', err);
    }
}

async function requestMediaAndCall(targetPeerId, targetUserId) {
    // Если уже есть соединение — не создаём новое
    if (peerConnection) {
        console.log('⚠️ Уже есть соединение — пропускаю');
        return;
    }
    
    console.log('📞 Начинаю звонок к:', targetPeerId, 'user_id:', targetUserId);
    remotePeerId = targetPeerId;
    
    // Создаём RTCPeerConnection с TURN серверами
    const config = {
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            {
                urls: 'turn:136.234.79.6:3478?transport=udp',
                username: 'workspace_user',
                credential: 'workspace_turn_pass_2026'
            },
            {
                urls: 'turn:136.234.79.6:3478?transport=tcp',
                username: 'workspace_user',
                credential: 'workspace_turn_pass_2026'
            }
        ]
    };
    
    peerConnection = new RTCPeerConnection(config);
    
    // Добавляем локальный поток
    localStream.getTracks().forEach(function(track) {
        peerConnection.addTrack(track, localStream);
    });
    
    // Когда получаем поток от собеседника
    peerConnection.ontrack = function(event) {
        console.log('✅ Получен поток от собеседника');
        addRemoteVideo(targetPeerId, event.streams[0]);
    };
    
    // Отправляем ICE кандидаты
    peerConnection.onicecandidate = function(event) {
        if (event.candidate) {
            console.log('📤 ICE кандидат готов, target:', targetUserId);
            socket.emit('send_ice', {
                target_user_id: targetUserId,
                room_id: currentRoom,
                ice_candidate: event.candidate,
                peer_id: currentPeerId
            });
        }
    };
    
    // Обработка ошибок соединения
    peerConnection.onconnectionstatechange = function() {
        console.log('🔗 Состояние соединения:', peerConnection.connectionState);
        if (peerConnection.connectionState === 'failed') {
            console.error('❌ Соединение упало');
        }
    };
    
    // Создаём offer
    try {
        console.log('📤 Создаём SDP offer...');
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        
        // Отправляем SDP offer через SocketIO
        console.log('📤 Отправляю SDP offer target_user_id:', targetUserId, 'peer_id:', currentPeerId);
        
        // Retry mechanism — ждём пока собеседник присоединится
        let retries = 0;
        const maxRetries = 10;
        
        function sendSDPOffer() {
            socket.emit('send_sdp', {
                target_user_id: targetUserId,
                room_id: currentRoom,
                sdp: offer,
                peer_id: currentPeerId
            });
            
            // Если не получили ответ через 3 секунды — пробуем снова
            setTimeout(() => {
                if (retries < maxRetries && !peerConnection.remoteDescription) {
                    retries++;
                    console.log(`🔄 Retry ${retries}/${maxRetries} — SDP ещё не принят`);
                    sendSDPOffer();
                }
            }, 3000);
        }
        
        sendSDPOffer();
        console.log('📤 SDP offer отправлен');
    } catch (err) {
        console.error('❌ Ошибка создания offer:', err);
    }
}

async function handleSDP(sdp, fromPeerId, fromUserId) {
    console.log('📥 Получен SDP от:', fromPeerId, 'user_id:', fromUserId);
    remotePeerId = fromPeerId;
    
    if (!peerConnection) {
        // Создаём PeerConnection для ответа
        console.log('🔧 Создаём PeerConnection для ответа');
        const config = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                {
                    urls: 'turn:136.234.79.6:3478?transport=udp',
                    username: 'workspace_user',
                    credential: 'workspace_turn_pass_2026'
                }
            ]
        };
        
        peerConnection = new RTCPeerConnection(config);
        
        localStream.getTracks().forEach(function(track) {
            peerConnection.addTrack(track, localStream);
        });
        
        peerConnection.ontrack = function(event) {
            console.log('✅ Получен поток от собеседника');
            addRemoteVideo(fromPeerId, event.streams[0]);
        };
        
        peerConnection.onicecandidate = function(event) {
            if (event.candidate) {
                console.log('📤 ICE кандидат готов, target:', fromUserId);
                socket.emit('send_ice', {
                    target_user_id: fromUserId,
                    room_id: currentRoom,
                    ice_candidate: event.candidate,
                    peer_id: currentPeerId
                });
            }
        };
    }
    
    try {
        console.log('📥 Устанавливаем remote description...');
        await peerConnection.setRemoteDescription(new RTCSessionDescription(sdp));
        
        // Создаём answer
        console.log('📤 Создаём SDP answer...');
        const answer = await peerConnection.createAnswer();
        await peerConnection.setLocalDescription(answer);
        
        // Отправляем answer
        console.log('📤 Отправляю SDP answer target_user_id:', fromUserId);
        socket.emit('send_sdp', {
            target_user_id: fromUserId,
            room_id: currentRoom,
            sdp: answer,
            peer_id: currentPeerId
        });
        
        console.log('📤 SDP answer отправлен');
    } catch (err) {
        console.error('❌ Ошибка обработки SDP:', err);
    }
}

async function handleICE(iceCandidate, fromPeerId) {
    try {
        await peerConnection.addIceCandidate(new RTCIceCandidate(iceCandidate));
        console.log('✅ ICE кандидат добавлен');
    } catch (err) {
        console.error('❌ Ошибка ICE:', err);
    }
}

function addRemoteVideo(peerId, stream) {
    console.log('➕ Добавляем удалённое видео для:', peerId);
    let container = document.getElementById('video-' + peerId);
    
    if (!container) {
        container = document.createElement('div');
        container.id = 'video-' + peerId;
        container.className = 'video-container';
        container.innerHTML = `
            <video id="remoteVideo-${peerId}" autoplay playsinline style="width: 100%; height: auto; border-radius: 8px; background: #1a1a2e;"></video>
            <div class="video-label">Собеседник</div>
        `;
        document.getElementById('videoGrid').appendChild(container);
    }
    
    const video = document.getElementById('remoteVideo-' + peerId);
    if (video) {
        video.srcObject = stream;
        console.log('✅ Видео установлено');
    }
}

function removeRemoteVideo(peerId) {
    const container = document.getElementById('video-' + peerId);
    if (container) {
        container.remove();
    }
}

function toggleMute() {
    if (!localStream) return;
    localStream.getAudioTracks().forEach(track => {
        track.enabled = !track.enabled;
    });
    const icon = document.getElementById('micIcon');
    if (icon) {
        icon.className = localStream.getAudioTracks()[0].enabled ? 'bi bi-mic' : 'bi bi-mic-mute';
    }
}

function toggleVideo() {
    if (!localStream) return;
    localStream.getVideoTracks().forEach(track => {
        track.enabled = !track.enabled;
    });
    const icon = document.getElementById('videoIcon');
    if (icon) {
        icon.className = localStream.getVideoTracks()[0].enabled ? 'bi bi-camera' : 'bi bi-camera-off';
    }
}

function leaveRoom() {
    if (!confirm('Выйти из комнаты?')) return;
    
    if (socket) socket.disconnect();
    if (localStream) {
        localStream.getTracks().forEach(function(track) { track.stop(); });
    }
    
    window.location.href = '/video/conference';
}

function endConference() {
    if (!confirm('Завершить конференцию?')) return;
    
    if (socket) socket.disconnect();
    if (localStream) {
        localStream.getTracks().forEach(function(track) { track.stop(); });
    }
    
    window.location.href = '/video/conference';
}

// Инициализация при загрузке
document.addEventListener('DOMContentLoaded', function() {
    if (ROOM_ID) {
        initPeerJS(ROOM_ID);
    }
});
