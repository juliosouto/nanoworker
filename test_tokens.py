import sys
import os
import json
sys.path.append('/Users/juliosouto/projects/nanoworker')
from tools import get_permitted_tools
from google.genai import types

tools = get_permitted_tools()
print(f"Number of tools: {len(tools)}")
