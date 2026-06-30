"""
ASGI config for campusflow project — HTTP + WebSocket (Django Channels).
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")

# Initialise Django apps BEFORE importing channel consumers
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from campusflow_app.consumers.bus_tracking import BusTrackingConsumer

websocket_urlpatterns = [
    path("ws/bus-tracking/", BusTrackingConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})

