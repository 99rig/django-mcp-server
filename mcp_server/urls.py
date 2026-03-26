"""
URL configuration for MCP server endpoint.
"""
from django.urls import path
from .views import MCPView

app_name = 'mcp_server'

urlpatterns = [
    path('mcp/', MCPView.as_view(), name='mcp-endpoint'),
]
