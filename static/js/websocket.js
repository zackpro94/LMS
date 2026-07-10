// WebSocket client for real-time notifications
class WebSocketClient {
    constructor() {
        this.socket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 3000;
        this.isConnected = false;
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws/notifications/`;

        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => {
            console.log('WebSocket connected');
            this.isConnected = true;
            this.reconnectAttempts = 0;
        };

        this.socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };

        this.socket.onclose = (event) => {
            console.log('WebSocket disconnected');
            this.isConnected = false;
            this.attemptReconnect();
        };

        this.socket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`);
            setTimeout(() => this.connect(), this.reconnectDelay);
        }
    }

    handleMessage(data) {
        if (data.type === 'notification') {
            this.handleNotification(data.notification);
        } else if (data.type === 'letter_update') {
            this.handleLetterUpdate(data.letter);
        }
    }

    handleNotification(notification) {
        // Update notification bell
        const notificationBell = document.querySelector('.notification-bell');
        if (notificationBell) {
            const badge = notificationBell.querySelector('.badge');
            if (badge) {
                const currentCount = parseInt(badge.textContent) || 0;
                badge.textContent = currentCount + 1;
                badge.classList.remove('d-none');
            }
        }

        // Show toast notification
        this.showToast(notification.title, notification.message);
        
        // Play notification sound
        this.playNotificationSound();
    }

    handleLetterUpdate(letter) {
        // Refresh letter list if on letter list page
        if (window.location.pathname === '/letters/' || window.location.pathname === '/') {
            // Reload the page or update the list dynamically
            window.location.reload();
        }
    }

    showToast(title, message) {
        // Check if toast container exists
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(container);
        }

        const toastId = 'toast-' + Date.now();
        const toastHtml = `
            <div id="${toastId}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header">
                    <strong class="me-auto">${title}</strong>
                    <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', toastHtml);
        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement);
        toast.show();

        // Remove toast after it's hidden
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
    }

    playNotificationSound() {
        // Check if sound is enabled
        const soundEnabled = localStorage.getItem('soundNotificationsEnabled') === 'true';
        if (soundEnabled) {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            oscillator.frequency.value = 800;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.1;
            
            oscillator.start();
            oscillator.stop(audioContext.currentTime + 0.2);
        }
    }

    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }
}

// Initialize WebSocket when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    if (typeof bootstrap !== 'undefined') {
        window.wsClient = new WebSocketClient();
        window.wsClient.connect();
    }
});

// Disconnect WebSocket when page is unloaded
window.addEventListener('beforeunload', () => {
    if (window.wsClient) {
        window.wsClient.disconnect();
    }
});
