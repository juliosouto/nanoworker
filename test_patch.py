import subprocess
import os

_original_popen_init = subprocess.Popen.__init__
def _patched_popen_init(self, args, **kwargs):
    if 'close_fds' not in kwargs:
        kwargs['close_fds'] = False
        
    executable = kwargs.get('executable')
    import shutil
    if executable is None:
        if isinstance(args, (str, bytes, os.PathLike)):
            cmd = args
        else:
            cmd = args[0] if args else None
            
        if cmd and isinstance(cmd, str) and not os.path.dirname(cmd):
            resolved = shutil.which(cmd)
            if resolved:
                if isinstance(args, list):
                    args = list(args)
                    args[0] = resolved
                elif isinstance(args, tuple):
                    args = list(args)
                    args[0] = resolved
                    args = tuple(args)
                else:
                    kwargs['executable'] = resolved

    print(f"args to original: {args}")
    return _original_popen_init(self, args, **kwargs)

subprocess.Popen.__init__ = _patched_popen_init

print("Calling run with ls:")
subprocess.run(["ls"], capture_output=True)
