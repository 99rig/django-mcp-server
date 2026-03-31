"""
Decorators for registering MCP tools, resources, and prompts.
"""
import inspect
from functools import wraps
from .registry import registry
from .schema import generate_schema_from_hints


def mcp_tool(name=None, description="", condition=None):
    """
    Decorator to register a function as an MCP tool.

    If the function has a `user` parameter, it will be injected automatically
    by the auth layer and excluded from the MCP input schema.

    Args:
        name: Tool name (defaults to function name)
        description: Tool description for AI agents
        condition: Optional callable(user) -> bool. If provided, the tool is
                   only listed/callable when condition(user) returns True.

    Example (no auth):
        @mcp_tool(name="search_products", description="Search for products")
        def search_products(query: str, limit: int = 10):
            return Product.objects.filter(name__icontains=query)[:limit]

    Example (with user context):
        @mcp_tool(description="Get my listings")
        def get_my_listing(user):
            return Immobile.objects.filter(venditore__user=user).values(...)

    Example (conditional tool):
        @mcp_tool(description="Seller-only tool", condition=lambda u: hasattr(u, 'venditore'))
        def publish_listing(user, listing_id: int):
            ...
    """
    def decorator(func):
        tool_name = name or func.__name__

        # Detect if the function declares a `user` parameter
        sig = inspect.signature(func)
        needs_user = 'user' in sig.parameters

        # Generate input schema (excludes `user` parameter automatically)
        input_schema = generate_schema_from_hints(func)

        # Register the tool
        registry.register_tool(tool_name, func, description, input_schema, needs_user, condition)

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
