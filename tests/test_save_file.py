import sys
import os

# Ensure the root project directory is in PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.macos.save_file import save_file_to_disk

def test_save():
    print("Testing save_file_to_disk...")
    result = save_file_to_disk("Hello from the new tool!", "hello_world.txt", "documents")
    print("Result:", result)
    
    expected_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files", "documents", "hello_world.txt")
    if os.path.exists(expected_path):
        print("Success! File found at:", expected_path)
        with open(expected_path, 'r') as f:
            print("Content:", f.read())
    else:
        print("Failed! File not found at:", expected_path)

if __name__ == "__main__":
    test_save()
