import os
import importlib
import inspect

AVAILABLE_SELF_DEVELOPED_TOOLS = []

current_dir = os.path.dirname(__file__)
for filename in os.listdir(current_dir):
    if filename.endswith(".py") and filename != "__init__.py":
        module_name = filename[:-3]
        try:
            module = importlib.import_module(f".{module_name}", package=__name__)
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if obj.__module__ == module.__name__ and not obj.__name__.startswith("_"):
                    AVAILABLE_SELF_DEVELOPED_TOOLS.append(obj)
        except Exception as e:
            print(f"Error loading self-developed tool {module_name}: {e}")
