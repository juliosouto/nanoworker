import sys
sys.path.append('.')
from utils.message_utils import should_process_wa_message

print("Test User Audio (no mention):", should_process_wa_message("5511999999999", "[Audio received, waiting for transcription...]\n[Transcription]: blablabla", is_group=True))
print("Test User Audio (mention):", should_process_wa_message("5511999999999", "[Audio received, waiting for transcription...]\n[Transcription]: janja blablabla", is_group=True))
