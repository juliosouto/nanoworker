import platform
import os
import inspect
import importlib
import sys
from database import get_config
from utils.file_utils import read_file, write_file

OS_PLATFORM = platform.system()

# Start with tools from outside the tools/ directory
AVAILABLE_TOOLS = [read_file, write_file]

def _load_tools_from_directory(directory_path, package_prefix):
    if not os.path.isdir(directory_path):
        return
    for filename in os.listdir(directory_path):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            full_module_name = f"{package_prefix}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    # Only append functions actually defined in that module and not private
                    if getattr(obj, '__module__', None) == module.__name__ and not obj.__name__.startswith("_"):
                        if obj not in AVAILABLE_TOOLS:
                            AVAILABLE_TOOLS.append(obj)
            except Exception as e:
                print(f"Error loading tool {full_module_name}: {e}")

current_dir = os.path.dirname(__file__)

# 1. Load OS-specific tools from tools/<os_folder>/
os_folder = "macos"
if OS_PLATFORM == "Windows":
    os_folder = "windows"
elif OS_PLATFORM == "Linux":
    os_folder = "linux"

os_dir = os.path.join(current_dir, os_folder)
_load_tools_from_directory(os_dir, f"tools.{os_folder}")

# 2. Load root tools from tools/ (if any exist in the root)
_load_tools_from_directory(current_dir, "tools")

# 3. Load self-developed OS-specific tools (if available)
try:
    if OS_PLATFORM == "Windows":
        mod = importlib.import_module('tools.self-developed.windows')
    elif OS_PLATFORM == "Linux":
        mod = importlib.import_module('tools.self-developed.linux')
    else:
        mod = importlib.import_module('tools.self-developed.macos')
    
    if hasattr(mod, 'AVAILABLE_SELF_DEVELOPED_TOOLS'):
        for obj in mod.AVAILABLE_SELF_DEVELOPED_TOOLS:
            if obj not in AVAILABLE_TOOLS:
                AVAILABLE_TOOLS.append(obj)
except Exception:
    pass

def get_permitted_tools():
    """Returns a list of tools filtered by the user's specific tool settings."""
    tools = []
    
    for tool_func in list(AVAILABLE_TOOLS):
        # Verify self-developed tool file still exists
        mod_name = getattr(tool_func, '__module__', '')
        if 'self_developed' in mod_name or 'self-developed' in mod_name:
            if mod_name in sys.modules:
                module = sys.modules[mod_name]
                if hasattr(module, '__file__') and module.__file__:
                    if not os.path.exists(module.__file__):
                        AVAILABLE_TOOLS.remove(tool_func)
                        continue

        tool_name = tool_func.__name__
        # Se for verdadeiro (default = 'true'), a ferramenta é disponibilizada
        if get_config(f'TOOL_{tool_name.upper()}', 'true').lower() == 'true':
            tools.append(tool_func)
            
    return tools
