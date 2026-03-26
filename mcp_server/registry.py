"""
MCP Registry - Singleton that tracks all registered tools, resources, and prompts.
"""
from dataclasses import dataclass
from typing import Callable, Dict, Any, Optional


@dataclass
class ToolDefinition:
    """Represents a registered MCP tool."""
    name: str
    func: Callable
    description: str
    input_schema: Dict[str, Any]


@dataclass
class ResourceDefinition:
    """Represents a registered MCP resource."""
    uri: str
    func: Callable
    name: str
    description: str
    mime_type: str


@dataclass
class PromptDefinition:
    """Represents a registered MCP prompt."""
    name: str
    func: Callable
    description: str
    arguments: list


class MCPRegistry:
    """
    Singleton registry for MCP tools, resources, and prompts.
    
    All @mcp_tool, @mcp_resource, @mcp_prompt decorators register here.
    """
    _instance: Optional['MCPRegistry'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.tools = {}
            cls._instance.resources = {}
            cls._instance.prompts = {}
        return cls._instance
    
    def register_tool(self, name: str, func: Callable, description: str, input_schema: Dict[str, Any]):
        """Register a tool."""
        self.tools[name] = ToolDefinition(name, func, description, input_schema)
    
    def register_resource(self, uri: str, func: Callable, name: str, description: str, mime_type: str):
        """Register a resource."""
        self.resources[uri] = ResourceDefinition(uri, func, name, description, mime_type)
    
    def register_prompt(self, name: str, func: Callable, description: str, arguments: list):
        """Register a prompt."""
        self.prompts[name] = PromptDefinition(name, func, description, arguments)
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self.tools.get(name)
    
    def get_resource(self, uri: str) -> Optional[ResourceDefinition]:
        """Get a resource by URI."""
        return self.resources.get(uri)
    
    def list_tools(self) -> list:
        """List all registered tools."""
        return list(self.tools.values())
    
    def list_resources(self) -> list:
        """List all registered resources."""
        return list(self.resources.values())
    
    def list_prompts(self) -> list:
        """List all registered prompts."""
        return list(self.prompts.values())


# Global registry instance
registry = MCPRegistry()
