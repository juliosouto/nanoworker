import subprocess
import os

_original_popen_init = subprocess.Popen.__init__
def _patched_popen_init(self, args, **kwargs):
    kwargs['close_fds'] = False
    
    class MockPopen:
        def _execute_child(self, args, executable, preexec_fn, close_fds, *args_, **kwargs_):
            print(f"USE_POSIX_SPAWN? {bool(os.path.dirname(executable)) and not close_fds}")
            
    self._execute_child = MockPopen()._execute_child
    return _original_popen_init(self, args, **kwargs)

subprocess.Popen.__init__ = _patched_popen_init

print("Testing with stderr=2")
try: subprocess.run(["/bin/ls"], stderr=2)
except Exception as e: pass

