"""
django-mcp-server - Full MCP server implementation for Django.

Expose tools and resources to AI agents via the Model Context Protocol.
"""

__version__ = '0.1.0'

from .decorators import mcp_tool, mcp_resource, mcp_prompt
from .registry import registry

__all__ = [
    'mcp_tool',
    'mcp_resource',
    'mcp_prompt',
    'registry',
]

# Django app config
default_app_config = 'mcp_server.apps.McpServerConfig'
