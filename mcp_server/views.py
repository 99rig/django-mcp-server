"""
MCP JSON-RPC 2.0 endpoint view.
"""
import json
from django.views import View
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .registry import registry


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
    """
    
    def post(self, request):
        """Handle JSON-RPC 2.0 requests."""
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
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
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
            "protocolVersion": "2025-06-18",
            "capabilities": capabilities,
            "serverInfo": {
                "name": getattr(settings, 'MCP_SERVER_NAME', 'Django MCP Server'),
                "version": getattr(settings, 'MCP_SERVER_VERSION', '0.1.0'),
            }
        }
    
    def _handle_tools_list(self, params):
        """List all registered tools."""
        tools = []
        for tool in registry.list_tools():
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            })
        
        return {"tools": tools}
    
    def _handle_tools_call(self, params):
        """Execute a tool."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        # MCP-002 fix: explicit allowlist check BEFORE parsing arguments
        tool = registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Validate arguments against inputSchema before execution
        self._validate_arguments(arguments, tool.input_schema)

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
