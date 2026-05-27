import sys
import inspect
from database import get_config
from tools import get_permitted_tools

permitted_tools = get_permitted_tools()
tools_length = 0
json_overhead = len(permitted_tools) * 15

for t in permitted_tools:
    tools_length += len(t.__name__)
    if t.__doc__:
        tools_length += len(str(t.__doc__))
        
    try:
        sig = inspect.signature(t)
        for param_name, param in sig.parameters.items():
            tools_length += len(param_name)
            if param.annotation != inspect.Parameter.empty:
                tools_length += len(str(param.annotation))
    except Exception:
        pass
        
tools_tokens = (tools_length // 4) + json_overhead
print(f"Tools count: {len(permitted_tools)}, Tokens: {tools_tokens}")
