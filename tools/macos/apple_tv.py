import asyncio
import threading
import json
import logging
import pyatv
from pyatv.const import Protocol

logger = logging.getLogger(__name__)

def _get_apple_tv_config():
    from database import get_db, decrypt_value
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT private_key FROM tools_config WHERE tool_name = ?', ('control_apple_tv',))
    row = cursor.fetchone()
    conn.close()
    if row and row['private_key']:
        try:
            decrypted = decrypt_value(row['private_key'])
            return json.loads(decrypted)
        except Exception as e:
            logger.error(f"Failed to parse Apple TV config: {e}")
            return None
    return None

class AppleTVManager:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start_loop, daemon=True)
        self.atv = None
        self.thread.start()
        
    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _connect(self):
        config = _get_apple_tv_config()
        if not config:
            return False, "No configuration found for Apple TV. Please pair in Settings first."

        identifier = config.get('identifier')
        credentials = config.get('credentials')
        
        if not identifier or not credentials:
             return False, "Invalid Apple TV configuration."

        # Reconnect if config has changed (e.g., new pairing)
        if getattr(self, '_current_config', None) != config:
            if self.atv is not None:
                self.atv.close()
                self.atv = None
            self._current_config = config

        # Connection will be established freshly per command
        if self.atv is not None:
            self.atv.close()
            self.atv = None

        logger.info(f"Scanning for Apple TV with identifier: {identifier}")
        scans = await pyatv.scan(self.loop, identifier=identifier)
        if not scans:
             return False, "Apple TV not found on the network."
             
        conf = scans[0]
        # set credentials
        target_protocol = None
        for service_str, creds in credentials.items():
            try:
                protocol = Protocol(int(service_str))
                conf.set_credentials(protocol, creds)
                target_protocol = protocol
            except ValueError:
                pass
            
        try:
            logger.info("Connecting to Apple TV...")
            self.atv = await pyatv.connect(conf, self.loop)
            logger.info("Connected successfully.")
            return True, "Connected successfully."
        except Exception as e:
            logger.error(f"Apple TV connect error: {e}")
            return False, f"Failed to connect: {str(e)}"

    async def _execute_command(self, command: str):
        success, msg = await self._connect()
        if not success:
            return msg

        try:
            if command == "play":
                await self.atv.remote_control.play_pause()
            elif command == "pause":
                await self.atv.remote_control.play_pause()
            elif command == "next":
                await self.atv.remote_control.next()
            elif command == "previous":
                await self.atv.remote_control.previous()
            elif command == "menu":
                await self.atv.remote_control.menu()
            elif command == "volume_up":
                await self.atv.audio.volume_up()
            elif command == "volume_down":
                await self.atv.audio.volume_down()
            elif command == "turn_on":
                await self.atv.power.turn_on()
            elif command == "turn_off":
                await self.atv.power.turn_off()
            else:
                return f"Command '{command}' not recognized."
            return f"Command '{command}' executed successfully."
        except Exception as e:
            logger.error(f"Apple TV execute error: {e}")
            return f"Error executing command: {str(e)}"
        finally:
            if self.atv is not None:
                self.atv.close()
                self.atv = None

_manager = None

def control_apple_tv(command: str) -> str:
    """
    Controls an Apple TV on the local network. 
    Supported commands: play, pause, next, previous, menu, volume_up, volume_down, turn_on, turn_off.
    Requires the Apple TV to be paired in the UI tools settings first.
    """
    
    global _manager
    if _manager is None:
        _manager = AppleTVManager()
        
    future = asyncio.run_coroutine_threadsafe(_manager._execute_command(command.lower()), _manager.loop)
    try:
        result = future.result(timeout=15)
        return result
    except Exception as e:
        return f"Timeout or error waiting for Apple TV response: {str(e)}"
