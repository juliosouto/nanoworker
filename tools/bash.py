import subprocess
import os
from utils.security_utils import require_permission

@require_permission('PERM_TERMINAL')
def run_bash_command(command: str) -> str:
    """
    Executes a bash command on the local machine and returns its output.
    
    Args:
        command: The bash command to execute.
        
    Returns:
        The standard output and standard error of the command execution, or an error message.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120 # 2 minute timeout
        )
        
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}\n"
            
        if not output:
            output = f"Command '{command}' executed successfully with no output."
            
        return output
    except subprocess.TimeoutExpired:
        return f"Error: Command '{command}' timed out after 120 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"
