import os

def create_self_developed_tool(tool_name: str, code: str) -> str:
    """
    You can use this tool to autonomously create new tools.
    You have full access to the terminal, file system, etc., within the project folder.
    Provide the Python code for the new tool.
    The tool will be automatically saved to /tools/self-developed/linux/tool_name.py.
    
    IMPORTANT: The Python code MUST include type hints for all parameters and return values (e.g., param: str) and a Google-style docstring. Otherwise, the AI framework will fail to register the tool.
    Functions starting with an underscore (_) are treated as private helpers and will be ignored.
    
    Args:
        tool_name (str): The name of the python file to create (e.g., 'my_new_tool'). Do not include the .py extension.
        code (str): The valid Python code that implements the tool.
        
    Returns:
        str: A success or error message.
    """
    try:
        # Define base path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        os_name = "linux"
        target_dir = os.path.join(project_root, "tools", "self-developed", os_name)
        
        # --- DOUBLE-CHECK LOGIC ---
        try:
            from database import get_config, get_db, decrypt_value
            from utils.session import current_session_id
            
            double_check_enabled = get_config('TOOL_CREATOR_DOUBLE_CHECK', 'false').lower() == 'true'
            if double_check_enabled:
                session_id = current_session_id.get()
                user_prompt = "No user prompt found"
                if session_id:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute('SELECT content, created_at FROM messages_in WHERE session_id = ? ORDER BY created_at DESC LIMIT 1', (session_id,))
                    row1 = c.fetchone()
                    c.execute('SELECT content, created_at FROM ide_messages_in WHERE session_id = ? ORDER BY created_at DESC LIMIT 1', (session_id,))
                    row2 = c.fetchone()
                    conn.close()
                    
                    if row1 and row2:
                        if row1['created_at'] > row2['created_at']:
                            user_prompt = row1['content']
                        else:
                            user_prompt = row2['content']
                    elif row1:
                        user_prompt = row1['content']
                    elif row2:
                        user_prompt = row2['content']
                
                gemini_model = get_config("GEMINI_MODEL", "gemini-2.5-flash")
                gemini_key_enc = get_config("GEMINI_API_KEY")
                if gemini_key_enc:
                    api_key = decrypt_value(gemini_key_enc)
                    from google import genai
                    from google.genai import types
                    client = genai.Client(api_key=api_key)
                    
                    review_prompt = f"""You are an expert python developer evaluating a newly generated tool.
The user requested the following tool functionality:
{user_prompt}

The initial generated python code is:
```python
{code}
```

Please validate this code. Fix any bugs, ensure all parameters and return values have python type hints, and ensure there is a complete Google-style docstring for the tool function. If the tool is missing required imports, add them.
Return ONLY the final, complete, and valid Python code without any markdown wrappers or additional text if possible. If you must use markdown wrappers like ```python, ensure they are easily parseable."""
                    
                    chat = client.chats.create(
                        model=gemini_model,
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(thinking_budget=4000),
                            temperature=0.0
                        )
                    )
                    response = chat.send_message(review_prompt)
                    reviewed_code = response.text
                    
                    if reviewed_code:
                        if reviewed_code.startswith("```python"):
                            reviewed_code = reviewed_code[9:]
                        elif reviewed_code.startswith("```"):
                            reviewed_code = reviewed_code[3:]
                        if reviewed_code.endswith("```"):
                            reviewed_code = reviewed_code[:-3]
                        code = reviewed_code.strip()
        except Exception as e:
            print(f"Tool Creator Double-Check failed: {e}")
        # --------------------------
        
        # Ensure directories exist
        os.makedirs(target_dir, exist_ok=True)
        
        # Ensure __init__.py exists in self-developed
        self_dev_init = os.path.join(project_root, "tools", "self-developed", "__init__.py")
        if not os.path.exists(self_dev_init):
            with open(self_dev_init, "w", encoding="utf-8") as f:
                f.write("")
                
        # Ensure __init__.py exists in target_dir
        target_init = os.path.join(target_dir, "__init__.py")
        if not os.path.exists(target_init):
            loader_code = '''import importlib
import inspect
import os

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
'''
            with open(target_init, "w", encoding="utf-8") as f:
                f.write(loader_code)
                
        # Clean tool name
        tool_name = os.path.basename(tool_name)
        if tool_name.endswith('.py'):
            tool_name = tool_name[:-3]
            
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', tool_name):
            return "Error: tool_name must be a valid Python identifier (letters, numbers, underscores, no spaces)."
            
        if tool_name == "__init__":
            return "Error: Cannot name a tool '__init__'."
            
        # Write the tool file
        file_path = os.path.join(target_dir, f"{tool_name}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
            
        # Hot-reload the tool into the current running process
        import importlib
        import inspect
        import sys
        import tools
        
        module_name_full = f"tools.self-developed.{os_name}.{tool_name}"
        importlib.invalidate_caches()
        
        if module_name_full in sys.modules:
            module = importlib.reload(sys.modules[module_name_full])
        else:
            module = importlib.import_module(module_name_full)
            
        init_module_name = f"tools.self-developed.{os_name}"
        if init_module_name in sys.modules:
            init_module = sys.modules[init_module_name]
        else:
            init_module = importlib.import_module(init_module_name)
            
        new_functions = []
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if obj.__module__ == module.__name__ and not obj.__name__.startswith("_"):
                new_functions.append(obj)
                
        tools.AVAILABLE_TOOLS = [t for t in tools.AVAILABLE_TOOLS if getattr(t, '__module__', None) != module.__name__]
        tools.AVAILABLE_TOOLS.extend(new_functions)
        
        init_module.AVAILABLE_SELF_DEVELOPED_TOOLS = [t for t in init_module.AVAILABLE_SELF_DEVELOPED_TOOLS if getattr(t, '__module__', None) != module.__name__]
        init_module.AVAILABLE_SELF_DEVELOPED_TOOLS.extend(new_functions)
            
        return f"Successfully created self-developed tool '{tool_name}' at {file_path}"
    except Exception as e:
        return f"Error creating tool: {str(e)}"
