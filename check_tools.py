import sys
sys.path.append('/Users/juliosouto/projects/nanoworker')
import tools
from utils.message_utils import process_tools_for_llm

permitted = tools.get_permitted_tools()
processed = process_tools_for_llm(permitted)
print("Number of tools:", len(processed))
import inspect
total_chars = 0
for t in processed:
    doc = t.__doc__ if t.__doc__ else ""
    total_chars += len(doc)
    total_chars += len(inspect.getsource(t))
print("Total chars approx:", total_chars)
