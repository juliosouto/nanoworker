import sys
sys.path.append('.')
from database import get_config, set_config, encrypt_value, decrypt_value, cipher_suite

print("Cipher suite:", cipher_suite)
set_config('LOGIN_TOKEN', 'my-test-token')
print("Stored token:", get_config('LOGIN_TOKEN'))
