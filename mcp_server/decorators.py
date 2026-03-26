"""
Decorators for registering MCP tools, resources, and prompts.
"""
from functools import wraps
from .registry import registry
from .schema import generate_schema_from_hints


def mcp_tool(name=None, description=""):
    """
    Decorator to register a function as an MCP tool.
    
    Example:
        @mcp_tool(name="search_products", description="Search for products")
        def search_products(query: str, limit: int = 10):
            return Product.objects.filter(name__icontains=query)[:limit]
    
    Args:
        name: Tool name (defaults to function name)
        description: Tool description for AI agents
    """
    def decorator(func):
        tool_name = name or func.__name__
        
        # Generate input schema from type hints
        input_schema = generate_schema_from_hints(func)
        
        # Register the tool
        registry.register_tool(tool_name, func, description, input_schema)
        
        # Return original function unchanged
        return func
    
    return decorator


def mcp_resource(uri, name=None, description="", mime_type="application/json"):
    """
    Decorator to register a function as an MCP resource.
    
    Example:
        @mcp_resource(
            uri="catalog://products/{id}",
            name="Product",
            description="Product details",
            mime_type="application/json"
        )
        def get_product(id: int):
            p = Product.objects.get(pk=id)
            return {"id": p.id, "name": p.name}
    
    Args:
        uri: Resource URI template
        name: Resource name (defaults to function name)
        description: Resource description
        mime_type: MIME type of resource content
    """
    def decorator(func):
        resource_name = name or func.__name__
        
        # Register the resource
        registry.register_resource(uri, func, resource_name, description, mime_type)
        
        return func
    
    return decorator


def mcp_prompt(name=None, description="", arguments=None):
    """
    Decorator to register a function as an MCP prompt.
    
    Example:
        @mcp_prompt(
            name="analyze_product",
            description="Analyze product data",
            arguments=[{"name": "product_id", "description": "Product ID", "required": True}]
        )
        def analyze_product_prompt(product_id: int):
            p = Product.objects.get(pk=product_id)
            return f"Analyze this product: {p.name} - ${p.price}"
    
    Args:
        name: Prompt name (defaults to function name)
        description: Prompt description
        arguments: List of prompt arguments
    """
    def decorator(func):
        prompt_name = name or func.__name__
        prompt_args = arguments or []
        
        # Register the prompt
        registry.register_prompt(prompt_name, func, description, prompt_args)
        
        return func
    
    return decorator
