# mcp-django-server

Full MCP (Model Context Protocol) server implementation for Django. Expose tools and resources to AI agents with simple decorators.

## Features

- 🚀 **Simple decorators** - `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`
- 🔄 **Auto-discovery** - Automatically finds `mcp_tools.py` in all Django apps
- 📝 **Type-safe** - Generates JSON Schema from Python type hints
- 🎯 **MCP compliant** - Full JSON-RPC 2.0 implementation (spec 2025-06-18)
- 🔧 **Zero config** - Works out of the box

## Installation

```bash
pip install mcp-django-server
```

## Quick Start

### 1. Add to INSTALLED_APPS

```python
# settings.py
INSTALLED_APPS = [
    ...
    'mcp_server',
]

# Optional configuration
MCP_SERVER_NAME = "My Django MCP Server"
MCP_SERVER_VERSION = "1.0.0"
```

### 2. Include URLs

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    ...
    path('', include('mcp_server.urls')),
]
```

### 3. Create tools

Create `mcp_tools.py` in any Django app:

```python
# myapp/mcp_tools.py
from mcp_server import mcp_tool, mcp_resource
from .models import Product

@mcp_tool(
    name="search_products",
    description="Search products by name and category"
)
def search_products(query: str, category: str = None, limit: int = 10):
    """Search products - automatically exposed via /mcp/ endpoint."""
    qs = Product.objects.filter(name__icontains=query)
    if category:
        qs = qs.filter(category=category)
    return [
        {"id": p.id, "name": p.name, "price": str(p.price)}
        for p in qs[:limit]
    ]

@mcp_resource(
    uri="catalog://products/{id}",
    name="Product",
    description="Full product details",
    mime_type="application/json"
)
def get_product(id: int):
    """Get product by ID - exposed as MCP resource."""
    p = Product.objects.get(pk=id)
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": str(p.price)
    }
```

### 4. Test it

```bash
# Initialize
curl -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","clientInfo":{"name":"test"}}}'

# List tools
curl -X POST http://localhost:8000/mcp/ \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call tool
curl -X POST http://localhost:8000/mcp/ \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_products","arguments":{"query":"laptop"}}}'
```

## API Reference

### @mcp_tool

Register a function as an MCP tool.

```python
@mcp_tool(name="tool_name", description="Tool description")
def my_tool(param1: str, param2: int = 10):
    return {"result": "value"}
```

**Parameters:**
- `name` (str, optional): Tool name. Defaults to function name.
- `description` (str): Tool description for AI agents.

**Type Hints:**
- Function type hints are automatically converted to JSON Schema
- Supported types: `str`, `int`, `float`, `bool`, `list`, `dict`
- Parameters without defaults are marked as required

### @mcp_resource

Register a function as an MCP resource.

```python
@mcp_resource(
    uri="catalog://items/{id}",
    name="Item",
    description="Item details",
    mime_type="application/json"
)
def get_item(id: int):
    return {"id": id, "data": "..."}
```

**Parameters:**
- `uri` (str): Resource URI template with `{param}` placeholders
- `name` (str, optional): Resource name. Defaults to function name.
- `description` (str): Resource description
- `mime_type` (str): MIME type. Default: "application/json"

### @mcp_prompt

Register a function as an MCP prompt template.

```python
@mcp_prompt(
    name="analyze",
    description="Analyze data",
    arguments=[
        {"name": "data_id", "description": "Data ID", "required": True}
    ]
)
def analyze_prompt(data_id: int):
    return f"Analyze data with ID: {data_id}"
```

## MCP Endpoints

Once installed, your Django app exposes:

- `POST /mcp/` - Main MCP JSON-RPC 2.0 endpoint

**Supported methods:**
- `initialize` - Initialize MCP session
- `tools/list` - List all registered tools
- `tools/call` - Execute a tool
- `resources/list` - List all resources
- `resources/read` - Read a resource
- `prompts/list` - List all prompts
- `prompts/get` - Get a prompt

## Integration with django-mcp-discovery

If you have `django-mcp-discovery` installed, this package automatically updates the `/.well-known/mcp-server` manifest with registered tools.

## Examples

### Django ORM Tool

```python
@mcp_tool(description="Get user by email")
def get_user(email: str):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.get(email=email)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.get_full_name()
    }
```

### External API Tool

```python
@mcp_tool(description="Get weather forecast")
def get_weather(city: str):
    import requests
    response = requests.get(f"https://api.weather.com/{city}")
    return response.json()
```

### File Resource

```python
@mcp_resource(
    uri="files://{path}",
    description="Read file content",
    mime_type="text/plain"
)
def read_file(path: str):
    with open(path, 'r') as f:
        return f.read()
```

## License

MIT

## Links

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [MCP Standard](https://mcpstandard.dev)
- [GitHub Repository](https://github.com/99rig/mcp-django-server)
