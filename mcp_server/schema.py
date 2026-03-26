"""
JSON Schema generation from Python type hints.
"""
import inspect
from typing import get_type_hints, get_origin, get_args


def generate_schema_from_hints(func) -> dict:
    """
    Generate JSON Schema from function type hints.
    
    Example:
        def search(query: str, limit: int = 10, active: bool = True)
        
        Returns:
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "active": {"type": "boolean"}
            },
            "required": ["query"]
        }
    """
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}
    
    sig = inspect.signature(func)
    
    properties = {}
    required = []
    
    for param_name, param in sig.parameters.items():
        # Skip self/cls
        if param_name in ('self', 'cls'):
            continue
        
        # Get type hint
        type_hint = hints.get(param_name, str)
        
        # Convert Python type to JSON Schema type
        json_type = python_type_to_json_schema(type_hint)
        properties[param_name] = json_type
        
        # Mark as required if no default value
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    
    schema = {
        "type": "object",
        "properties": properties
    }
    
    if required:
        schema["required"] = required
    
    return schema


def python_type_to_json_schema(type_hint) -> dict:
    """
    Convert a Python type hint to JSON Schema type definition.
    """
    # Basic types
    TYPE_MAP = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }
    
    # Direct mapping
    if type_hint in TYPE_MAP:
        return TYPE_MAP[type_hint]
    
    # Handle Optional[T] -> Union[T, None]
    origin = get_origin(type_hint)
    
    if origin is list:
        args = get_args(type_hint)
        if args:
            return {
                "type": "array",
                "items": python_type_to_json_schema(args[0])
            }
        return {"type": "array"}
    
    if origin is dict:
        return {"type": "object"}
    
    # Default to string
    return {"type": "string"}
