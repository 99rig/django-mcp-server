"""
MCP JSON-RPC 2.0 endpoint view.
"""
import json
import importlib
import logging
import re
import time
from django.views import View
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .registry import registry
from .constants import DEFAULT_PROTOCOL_VERSION

logger = logging.getLogger('mcp_server')

# Module-level cache for the auth backend instance (#4)
_auth_backend_cache: dict = {}


def _get_auth_backend():
    """
    Return a cached instance of the configured MCP_AUTH_BACKEND class.

    Loads and instantiates once per process; returns None if not configured.
    The class must implement: authenticate(token: str) -> User | None
    """
    backend_path = getattr(settings, 'MCP_AUTH_BACKEND', None)
    if not backend_path:
        return None
    if backend_path not in _auth_backend_cache:
        module_path, class_name = backend_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        _auth_backend_cache[backend_path] = cls()
    return _auth_backend_cache[backend_path]


# JSON Schema type map for argument validation (#10)
_JSON_TYPE_MAP = {
    'string': str,
    'integer': int,
    'number': (int, float),
    'boolean': bool,
    'array': list,
    'object': dict,
}


@method_decorator(csrf_exempt, name='dispatch')
class MCPView(View):
    """
    MCP JSON-RPC 2.0 endpoint.

    Handles:
    - initialize             (public — no auth required)
    - notifications/*        (public — no auth required)
    - tools/list
    - tools/call
    - resources/list
    - resources/read
    - prompts/list
    - prompts/get

    Authentication:
    Set MCP_AUTH_BACKEND in settings.py to a dotted path of a class that
    implements authenticate(token: str) -> User | None.
    Public methods are listed in MCP_PUBLIC_METHODS (default: initialize,
    notifications/initialized).

    Rate limiting:
    Set MCP_RATE_LIMIT = {"calls": N, "period": S} to enable per-user/IP
    rate limiting via Django's cache framework.

    Hooks (override in subclass):
    - before_dispatch(method, user)
    - after_tool_call(user, tool_name, result, duration_ms)
    """

    # Default public methods — no auth required (#1)
    DEFAULT_PUBLIC_METHODS = ['initialize', 'notifications/initialized']

    # ------------------------------------------------------------------ #
    # Hook methods — override in subclass for custom logic (#5)           #
    # ------------------------------------------------------------------ #

    def before_dispatch(self, method: str, user) -> None:
        """
        Called after auth/rate-limit but before the handler is executed.

        Override to add audit logging, custom authorization, etc.
        Raise an exception to abort the request.
        """

    def after_tool_call(self, user, tool_name: str, result, duration_ms: float) -> None:
        """
        Called after a tools/call completes successfully.

        Override to add audit logging, metrics, etc.
        """

    # ------------------------------------------------------------------ #
    # Auth                                                                #
    # ------------------------------------------------------------------ #

    def _authenticate(self, request):
        """
        Authenticate the request using the configured MCP_AUTH_BACKEND.

        Returns the authenticated user or None (no backend configured).
        Raises PermissionError if auth is required but fails.
        """
        backend = _get_auth_backend()
        if backend is None:
            return None

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            raise PermissionError("Missing or invalid Authorization header")

        token = auth_header[len('Bearer '):]
        user = backend.authenticate(token)
        if user is None:
            raise PermissionError("Invalid or expired token")

        return user

    # ------------------------------------------------------------------ #
    # Rate limiting (#8)                                                  #
    # ------------------------------------------------------------------ #

    def _check_rate_limit(self, request, user):
        """
        Enforce MCP_RATE_LIMIT = {"calls": N, "period": S} if configured.

        Uses Django's cache framework. Key is per-user (pk) or per-IP.
        Raises PermissionError when the limit is exceeded.
        """
        rate_limit = getattr(settings, 'MCP_RATE_LIMIT', None)
        if not rate_limit:
            return

        try:
            from django.core.cache import cache
        except ImportError:
            return

        max_calls = rate_limit.get('calls', 60)
        period = rate_limit.get('period', 60)

        identifier = str(getattr(user, 'pk', None) or request.META.get('REMOTE_ADDR', 'anon'))
        cache_key = f'mcp_ratelimit:{identifier}'

        count = cache.get(cache_key, 0)
        if count >= max_calls:
            raise PermissionError(f"Rate limit exceeded: {max_calls} calls per {period}s")

        # Increment; set TTL only on first call
        if count == 0:
            cache.set(cache_key, 1, timeout=period)
        else:
            cache.incr(cache_key)

    # ------------------------------------------------------------------ #
    # HTTP dispatch                                                        #
    # ------------------------------------------------------------------ #

    def get(self, request):
        """Return informative JSON for browser/discovery GET requests (#6)."""
        return JsonResponse({
            "server": getattr(settings, 'MCP_SERVER_NAME', 'Django MCP Server'),
            "version": getattr(settings, 'MCP_SERVER_VERSION', '0.1.0'),
            "protocol": "MCP JSON-RPC 2.0",
            "endpoint": request.build_absolute_uri(),
            "method": "POST",
            "tools": len(registry.list_tools()),
            "resources": len(registry.list_resources()),
            "prompts": len(registry.list_prompts()),
        })

    def post(self, request):
        """Handle JSON-RPC 2.0 requests."""
        # Parse body first so we can check the method (#1)
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return self._error(-32700, "Parse error")

        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id")

        # Determine public methods (skip auth for these) (#1)
        public_methods = getattr(settings, 'MCP_PUBLIC_METHODS', self.DEFAULT_PUBLIC_METHODS)
        is_public = method in public_methods

        # Authenticate non-public methods (#1, #2)
        user = None
        if not is_public:
            try:
                user = self._authenticate(request)
            except PermissionError as e:
                logger.warning("MCP auth failed for method=%s: %s", method, e)
                return self._error(-32000, str(e), req_id, http_status=401)

        # Rate limiting (#8)
        try:
            self._check_rate_limit(request, user)
        except PermissionError as e:
            logger.warning("MCP rate limit hit: %s", e)
            return self._error(-32000, str(e), req_id, http_status=429)

        # Check disabled_verbs
        disabled = getattr(settings, "MCP_DISABLED_VERBS", [])
        if method in disabled:
            return self._error(-32601, f"Method disabled: {method}", req_id)

        # Route to appropriate handler
        handlers = {
            "initialize": self._handle_initialize,
            "notifications/initialized": self._handle_notifications_initialized,  # (#3)
            "tools/list": lambda p: self._handle_tools_list(p, user),
            "tools/call": lambda p: self._handle_tools_call(p, user, request),
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }

        handler = handlers.get(method)
        if not handler:
            return self._error(-32601, f"Method not found: {method}", req_id)

        # before_dispatch hook (#5)
        try:
            self.before_dispatch(method, user)
        except Exception as e:
            return self._error(-32603, str(e), req_id)

        try:
            result = handler(params)
            if method == "initialize":
                logger.info("MCP initialize from %s", request.META.get('REMOTE_ADDR'))
            return JsonResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            })
        except Exception as e:
            logger.error("MCP error in method=%s: %s", method, e, exc_info=True)
            return self._error(-32603, str(e), req_id)

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _handle_initialize(self, params):
        """Handle initialize request."""
        capabilities = {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
            "prompts": {"listChanged": False},
        }

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

    def _handle_notifications_initialized(self, params):
        """No-op handler for notifications/initialized (#3)."""
        return {}

    def _handle_tools_list(self, params, user=None):
        """List all registered tools, filtered by condition if applicable."""
        tools = []
        for tool in registry.list_tools():
            if tool.condition is not None and not tool.condition(user):
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            })
        return {"tools": tools}

    def _handle_tools_call(self, params, user=None, request=None):
        """Execute a tool."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        tool = registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        if tool.condition is not None and not tool.condition(user):
            raise ValueError(f"Tool not available: {tool_name}")

        self._validate_arguments(arguments, tool.input_schema)

        if tool.needs_user:
            arguments = dict(arguments, user=user)

        t0 = time.monotonic()
        result = tool.func(**arguments)
        duration_ms = (time.monotonic() - t0) * 1000

        # after_tool_call hook (#5)
        try:
            self.after_tool_call(user, tool_name, result, duration_ms)
        except Exception:
            pass  # hooks must never break the response

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str)
                }
            ]
        }

    def _validate_arguments(self, arguments, schema):
        """
        Validate arguments against JSON Schema.

        Checks required fields, unknown keys, and basic types (#10).
        Raises ValueError if invalid.
        """
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field not in arguments:
                raise ValueError(f"Missing required argument: {field}")

        for key, value in arguments.items():
            if key not in properties:
                raise ValueError(f"Unknown argument: {key}")
            # Type validation (#10)
            expected_type = properties[key].get("type")
            if expected_type and expected_type in _JSON_TYPE_MAP:
                py_type = _JSON_TYPE_MAP[expected_type]
                # bool is a subclass of int in Python — check bool explicitly
                if expected_type == 'integer' and isinstance(value, bool):
                    raise ValueError(f"Argument '{key}': expected integer, got boolean")
                if not isinstance(value, py_type):
                    raise ValueError(
                        f"Argument '{key}': expected {expected_type}, "
                        f"got {type(value).__name__}"
                    )

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

        BLOCKED_SCHEMES = ["file://", "ftp://", "data:", "javascript:"]
        for scheme in BLOCKED_SCHEMES:
            if uri.lower().startswith(scheme):
                raise ValueError(f"URI scheme not allowed: {uri}")

        resource = None
        for r in registry.list_resources():
            if r.uri == uri or self._match_uri_template(r.uri, uri):
                resource = r
                break

        if not resource:
            raise ValueError(f"Resource not found: {uri}")

        uri_params = self._extract_uri_params(resource.uri, uri)
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

        prompt = registry.prompts.get(prompt_name)
        if not prompt:
            raise ValueError(f"Prompt not found: {prompt_name}")

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

    # ------------------------------------------------------------------ #
    # URI helpers                                                          #
    # ------------------------------------------------------------------ #

    def _match_uri_template(self, template, uri):
        """Match URI against template."""
        pattern = re.sub(r'\{[^}]+\}', r'[^/]+', template)
        return re.match(f'^{pattern}$', uri) is not None

    def _extract_uri_params(self, template, uri):
        """Extract parameters from URI based on template."""
        param_names = re.findall(r'\{([^}]+)\}', template)
        pattern = re.sub(r'\{[^}]+\}', r'([^/]+)', template)
        match = re.match(f'^{pattern}$', uri)
        if not match:
            return {}
        params = {}
        for i, name in enumerate(param_names):
            value = match.group(i + 1)
            try:
                value = int(value)
            except ValueError:
                pass
            params[name] = value
        return params

    # ------------------------------------------------------------------ #
    # Error helper (#9 — configurable HTTP status)                        #
    # ------------------------------------------------------------------ #

    def _error(self, code, message, req_id=None, http_status=400):
        """Return a JSON-RPC 2.0 error response with configurable HTTP status (#9)."""
        return JsonResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message
            }
        }, status=http_status)
