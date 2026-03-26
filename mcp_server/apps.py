"""
Django app configuration with auto-discovery of mcp_tools.py modules.
"""
from django.apps import AppConfig


class McpServerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mcp_server'
    verbose_name = 'MCP Server'
    
    def ready(self):
        """
        Auto-discover mcp_tools.py in all installed apps.
        
        Similar to how Django discovers admin.py, this will import
        mcp_tools.py from every installed app, triggering decorator
        registration.
        """
        from django.apps import apps
        import importlib
        
        for app_config in apps.get_app_configs():
            # Skip ourselves
            if app_config.name == 'mcp_server':
                continue
            
            try:
                importlib.import_module(f'{app_config.name}.mcp_tools')
            except ImportError:
                # No mcp_tools.py in this app, skip
                pass
            except Exception as e:
                # Log other errors but don't crash
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error loading mcp_tools from {app_config.name}: {e}")
