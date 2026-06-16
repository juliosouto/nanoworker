import sys
sys.path.append('/Users/juliosouto/projects/nanoworker')
from tools import get_permitted_tools
tools = get_permitted_tools()
print(f"Total tools: {len(tools)}")
for t in tools:
    print(t.__name__)
