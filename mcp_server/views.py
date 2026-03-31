"""
MCP JSON-RPC 2.0 endpoint view.
"""
import json
import importlib
from django.views import View
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .registry import registry
from .constants import DEFAULT_PROTOCOL_VERSION


def _load_auth_backend():
    """
    Load the custom auth backend class configured in MCP_AUTH_BACKEND.

    Expected format: 'myapp.mcp.auth.MyAuthClass'
    The class must implement: authenticate(token: str) -> User | None
    """
    backend_path = getattr(settings, 'MCP_AUTH_BACKEND', None)
    if not backend_path:
        return None
    module_path, class_name = backend_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


@method_decorator(csrf_exempt, name='dispatch')
class MCPView(View):
    """
    MCP JSON-RPC 2.0 endpoint.

    Handles:
    - initialize
    - tools/list
    - tools/call
    - resources/list
    - resources/read
    - prompts/list
    - prompts/get

    Authentication:
    Set MCP_AUTH_BACKEND in Django settings to a dotted path of a class that
    implements authenticate(token: str) -> User | None.
    If set, every request must include a valid Bearer token in the Authorization
    header. The authenticated user is injected into tools that declare a `user`
    parameter.
    """

    def _authenticate(self, request):
        """
        Authenticate the request using the configured MCP_AUTH_BACKEND.

        Returns the authenticated user or None (if no backend is configured).
        Raises PermissionError if auth is required but fails.
        """
        backend_class = _load_auth_backend()
        if backend_class is None:
            return None

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            raise PermissionError("Missing or invalid Authorization header")

        token = auth_header[len('Bearer '):]
        user = backend_class().authenticate(token)
        if user is None:
            raise PermissionError("Invalid or expired token")

        return user

    def post(self, request):
        """Handle JSON-RPC 2.0 requests."""
        # Authenticate before parsing body (avoids leaking method names on 401)
        try:
            user = self._authenticate(request)
        except PermissionError as e:
            return JsonResponse({"error": str(e)}, status=401)

        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return self._error(-32700, "Parse error")

        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id")

        # Check disabled_verbs (schema msaleme)
        disabled = getattr(settings, "MCP_DISABLED_VERBS", [])
        if method in disabled:
            return self._error(-32601, f"Method disabled: {method}", req_id)

        # Route to appropriate handler
        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": lambda p: self._handle_tools_list(p, user),
            "tools/call": lambda p: self._handle_tools_call(p, user),
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }

        handler = handlers.get(method)
        if not handler:
            return self._error(-32601, f"Method not found: {method}", req_id)

        try:
            result = handler(params)
            return JsonResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            })
        except Exception as e:
            return self._error(-32603, str(e), req_id)
    
    def _handle_initialize(self, params):
        """Handle initialize request."""
        capabilities = {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
            "prompts": {"listChanged": False},
        }

        # Add disabled_verbs if configured (schema msaleme)
        disabled = getattr(settings, "MCP_DISABLED_VERBS", [])
        if disabled:
            capabilities["disabled_verbs"] = disabled

        return {
            "protocolVersion": getattr(settings, 'MCP_PROTOCOL_VERSION', DEFAULT_PROTOCOL_VERSION),
            "capabilities": capabilities,
            "serverInfo": {
                "name": getattr(settings, 'MCP_SERVER_NAME', 'Django MCP Server'),
                "version": getattr(settings, 'MCP_SERVER_VERSION', '0.1.0'),
            }
        }
    
    def _handle_tools_list(self, params, user=None):
        """List all registered tools, filtered by condition if applicable."""
        tools = []
        for tool in registry.list_tools():
            # Skip tools whose condition is not satisfied for this user
            if tool.condition is not None and not tool.condition(user):
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            })

        return {"tools": tools}

    def _handle_tools_call(self, params, user=None):
        """Execute a tool."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        # MCP-002 fix: explicit allowlist check BEFORE parsing arguments
        tool = registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Check condition for the calling user
        if tool.condition is not None and not tool.condition(user):
            raise ValueError(f"Tool not available: {tool_name}")

        # Validate arguments against inputSchema before execution
        self._validate_arguments(arguments, tool.input_schema)

        # Inject authenticated user if the tool requests it
        if tool.needs_user:
            arguments = dict(arguments, user=user)

        # Execute the tool function
        result = tool.func(**arguments)

        # Wrap result in MCP content format
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str)
                }
            ]
        }
    
    def _validate_arguments(self, arguments, schema):
        """Validate arguments against JSON Schema. Raises ValueError if invalid."""
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        # Check required fields
        for field in required:
            if field not in arguments:
                raise ValueError(f"Missing required argument: {field}")

        # Check for unknown arguments
        for key in arguments:
            if key not in properties:
                raise ValueError(f"Unknown argument: {key}")

    def _handle_resources_list(self, params):
        """List all registered resources."""
        resources = []
        for resource in registry.list_resources():
            resources.append({
                "uri": resource.uri,
                "name": resource.name,
                "description": resource.description,
                "mimeType": resource.mime_type,
            })

        return {"resources": resources}
    
    def _handle_resources_read(self, params):
        """Read a resource."""
        uri = params.get("uri")

        # MCP-005 fix: reject dangerous URI schemes
        BLOCKED_SCHEMES = ["file://", "ftp://", "data:", "javascript:"]
        for scheme in BLOCKED_SCHEMES:
            if uri.lower().startswith(scheme):
                raise ValueError(f"URI scheme not allowed: {uri}")

        # Only allow URIs that match a registered resource template (allowlist)
        resource = None
        for r in registry.list_resources():
            if r.uri == uri or self._match_uri_template(r.uri, uri):
                resource = r
                break

        if not resource:
            raise ValueError(f"Resource not found: {uri}")

        # Extract parameters from URI
        uri_params = self._extract_uri_params(resource.uri, uri)

        # Execute resource function
        content = resource.func(**uri_params)

        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": json.dumps(content, ensure_ascii=False, default=str)
                }
            ]
        }
    
    def _handle_prompts_list(self, params):
        """List all registered prompts."""
        prompts = []
        for prompt in registry.list_prompts():
            prompts.append({
                "name": prompt.name,
                "description": prompt.description,
                "arguments": prompt.arguments,
            })
        
        return {"prompts": prompts}
    
    def _handle_prompts_get(self, params):
        """Get a prompt."""
        prompt_name = params.get("name")
        arguments = params.get("arguments", {})
        
        # Find prompt
        prompt = registry.prompts.get(prompt_name)
        if not prompt:
            raise ValueError(f"Prompt not found: {prompt_name}")
        
        # Execute prompt function
        result = prompt.func(**arguments)
        
        return {
            "description": prompt.description,
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": result
                    }
                }
            ]
        }
    
    def _match_uri_template(self, template, uri):
        """Match URI against template (simple implementation)."""
        # Replace {param} with regex pattern
        import re
        pattern = re.sub(r'\{[^}]+\}', r'[^/]+', template)
        pattern = f'^{pattern}$'
        return re.match(pattern, uri) is not None
    
    def _extract_uri_params(self, template, uri):
        """Extract parameters from URI based on template."""
        import re
        
        # Find parameter names in template
        param_names = re.findall(r'\{([^}]+)\}', template)
        
        # Build regex pattern to extract values
        pattern = re.sub(r'\{[^}]+\}', r'([^/]+)', template)
        pattern = f'^{pattern}$'
        
        match = re.match(pattern, uri)
        if not match:
            return {}
        
        # Build params dict
        params = {}
        for i, name in enumerate(param_names):
            value = match.group(i + 1)
            # Try to convert to int
            try:
                value = int(value)
            except ValueError:
                pass
            params[name] = value
        
        return params
    
    def _error(self, code, message, req_id=None):
        """Return JSON-RPC error response."""
        return JsonResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message
            }
        }, status=400)
