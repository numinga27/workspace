/**
 * Workspace App — логика нативной обёртки
 * Управляет бейджем, push-уведомлениями, offline-режимом
 */

import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { StatusBar, Style } from '@capacitor/status-bar';
import { Haptics, ImpactStyle } from '@capacitor/haptics';
import { Preferences } from '@capacitor/preferences';
import { Badge } from '@capawesome/capacitor-badge';
import { PushNotifications } from '@capacitor/push-notifications';

// ============================================================
//  ИНИЦИАЛИЗАЦИЯ
// ============================================================

async function init() {
    // Статус-бар
    if (Capacitor.isNativePlatform()) {
        await StatusBar.setStyle({ style: Style.Dark });
        await StatusBar.setBackgroundColor({ color: '#6366f1' });
    }

    // Обработка закрытия приложения
    App.addListener('appStateChange', (state) => {
        if (state.isActive) {
            // Приложение открыли — обновить бейдж
            updateBadgeFromServer();
        }
    });

    // Обработка push-уведомлений
    App.addListener('pushNotificationRegistered', async (data) => {
        console.log('Push token:', data.value);
        await Preferences.set({
            key: 'push_token',
            value: data.value,
        });
        // Отправляем токен на сервер
        sendTokenToServer(data.value);
    });

    App.addListener('pushNotificationReceive', async (data) => {
        console.log('Push received:', data);
        // Увеличиваем бейдж
        const current = parseInt(await Preferences.get({ key: 'badge_count' }).then(r => r.value || '0'));
        const newCount = current + 1;
        await Preferences.set({ key: 'badge_count', value: String(newCount) });
        await setBadge(newCount);
        Haptics.impact({ style: ImpactStyle.Medium });
    });

    // Первое открытие — запросить токен
    const token = await Preferences.get({ key: 'push_token' });
    if (!token.value) {
        requestPushPermission();
    }

    // Загружаем начальный бейдж
    updateBadgeFromServer();
}

// ============================================================
//  БЕЙДЖ
// ============================================================

async function setBadge(count) {
    if (!Capacitor.isNativePlatform()) return;
    await Badge.set({ value: count });
}

async function clearBadge() {
    if (!Capacitor.isNativePlatform()) return;
    await Badge.clear({});
}

async function updateBadgeFromServer() {
    if (!Capacitor.isNativePlatform()) return;
    
    try {
        // Получаем токен из localStorage (если залогинен)
        const token = localStorage.getItem('workspace_token');
        if (!token) return;
        
        const response = await fetch('https://workspace.your-domain.com/api/v1/unread-count', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        
        if (response.ok) {
            const data = await response.json();
            await setBadge(data.total || 0);
        }
    } catch (e) {
        console.warn('Failed to update badge:', e);
    }
}

// ============================================================
//  PUSH-УВЕДОМЛЕНИЯ
// ============================================================

async function requestPushPermission() {
    if (!Capacitor.isNativePlatform()) return;
    
    try {
        const status = await PushNotifications.requestPermissions();
        
        if (status.receive === 'granted') {
            await PushNotifications.register();
        }
    } catch (e) {
        console.warn('Push not available:', e);
    }
}

async function sendTokenToServer(token) {
    try {
        const wsToken = localStorage.getItem('workspace_token');
        if (!wsToken) return;
        
        await fetch('https://workspace.your-domain.com/api/v1/push/token', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${wsToken}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ token }),
        });
    } catch (e) {
        console.warn('Failed to send push token:', e);
    }
}

// ============================================================
//  ОФФЛАЙН-РЕЖИМ
// ============================================================

function setupOfflineDetection() {
    window.addEventListener('online', () => {
        console.log('Online — reconnecting');
        updateBadgeFromServer();
    });
    
    window.addEventListener('offline', () => {
        console.log('Offline');
    });
}

// ============================================================
//  ЗАПУСК
// ============================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        init();
        setupOfflineDetection();
    });
} else {
    init();
    setupOfflineDetection();
}
