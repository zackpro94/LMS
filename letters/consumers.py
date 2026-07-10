import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User


class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time notifications."""
    
    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close()
            return
        
        self.user = self.scope["user"]
        self.group_name = f"user_{self.user.id}"
        
        # Join user's personal notification group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        # Leave user's notification group
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        pass
    
    async def notification_message(self, event):
        """Send notification to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification': event['notification']
        }))
    
    async def letter_update(self, event):
        """Send letter update to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'letter_update',
            'letter': event['letter']
        }))
