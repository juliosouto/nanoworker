import sys
import os
sys.path.append('/Users/juliosouto/projects/nanoworker')
import tools
print([t.__name__ for t in tools.AVAILABLE_TOOLS])
