import base64
import logging
import os
import time
import uuid

from google.genai import types



def build_gemini_part(image_base64: str, mime_type: str = "image/jpeg", gemini_file_uri: str = None) -> types.Part | None:
    """
    Constrói um types.Part do Gemini a partir do base64 (podendo ser um raw base64, path: ou uri:).
    Usado principalmente para remontar o histórico sem fazer novos uploads.
    """
    if not mime_type:
        mime_type = "image/jpeg"
        
    if gemini_file_uri:
        return types.Part.from_uri(file_uri=gemini_file_uri, mime_type=mime_type)
    elif image_base64.startswith('uri:'):
        file_uri = image_base64[4:]
        return types.Part.from_uri(file_uri=file_uri, mime_type=mime_type)
    elif image_base64.startswith('path:'):
        file_path = image_base64[5:]
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                img_data = f.read()
            return types.Part.from_bytes(data=img_data, mime_type=mime_type)
        return None
    else:
        img_data = base64.b64decode(image_base64)
        return types.Part.from_bytes(data=img_data, mime_type=mime_type)

def upload_and_build_gemini_part(client, image_base64: str, mime_type: str = "image/jpeg", gemini_file_uri: str = None):
    """
    Constrói um types.Part, fazendo o upload do arquivo para o Gemini se necessário.
    Retorna uma tupla: (types.Part, new_gemini_uri).
    """
    if not mime_type:
        mime_type = "image/jpeg"
        
    if gemini_file_uri:
        return types.Part.from_uri(file_uri=gemini_file_uri, mime_type=mime_type), None
    elif image_base64.startswith('uri:'):
        file_uri = image_base64[4:]
        return types.Part.from_uri(file_uri=file_uri, mime_type=mime_type), None
    elif image_base64.startswith('path:'):
        file_path = image_base64[5:]
        if os.path.exists(file_path):
            if client:
                try:
                    uploaded_file = client.files.upload(file=file_path, config={"mime_type": mime_type})
                    while uploaded_file.state.name == "PROCESSING":
                        time.sleep(2)
                        uploaded_file = client.files.get(name=uploaded_file.name)
                        
                    if uploaded_file.state.name == "FAILED":
                        raise ValueError("Gemini failed to process the uploaded file.")
                        
                    return types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=mime_type), uploaded_file.uri
                except Exception as e:
                    logging.error(f"Failed to upload file to Gemini: {e}")
                    # Fallback para from_bytes se o upload falhar
                    with open(file_path, "rb") as f:
                        img_data = f.read()
                    return types.Part.from_bytes(data=img_data, mime_type=mime_type), None
            else:
                with open(file_path, "rb") as f:
                    img_data = f.read()
                return types.Part.from_bytes(data=img_data, mime_type=mime_type), None
        return None, None
    else:
        img_data = base64.b64decode(image_base64)
        return types.Part.from_bytes(data=img_data, mime_type=mime_type), None
