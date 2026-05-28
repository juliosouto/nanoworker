import hashlib
import os
import json
import shutil
from database import get_db

def save_extracted_document(category: str, extracted_data: dict, additional_metadata: dict = None, file_path: str = None) -> str:
    """
    Saves a document (PDF or image) to bin/docs/ using a hash of its content for the name,
    and stores the extracted data in the database.
    
    Args:
        category (str): The category of the document (e.g., 'invoice', 'receipt', 'contract').
        extracted_data (dict): The data extracted from the document, to be stored as JSON.
        additional_metadata (dict, optional): Any other important metadata, to be stored as JSON.
        file_path (str, optional): The path to the file. If not provided, the tool will automatically use the most recent image sent by the user.
        
    Returns:
        str: A success message indicating the saved file name and hash, or an error message.
    """
    file_content = None

    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                # Check if it's the agent's dummy file
                if b'dummy content' not in content:
                    file_content = content
        except Exception as e:
            pass

    # If no valid file_path or it was a dummy file, fetch the latest image from messages_in
    if not file_content:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT image_base64 FROM messages_in WHERE image_base64 IS NOT NULL ORDER BY created_at DESC LIMIT 1')
            row = cursor.fetchone()
            conn.close()
            if row and row['image_base64']:
                db_data = row['image_base64']
                if db_data.startswith('path:'):
                    # It's a local file path reference from WhatsApp
                    real_path = db_data[5:].strip()
                    if os.path.exists(real_path):
                        with open(real_path, 'rb') as f:
                            file_content = f.read()
                    else:
                        return f"Error: Referenced file path {real_path} not found."
                else:
                    import base64
                    file_content = db_data.encode('utf-8') # Will be decoded below
            else:
                return "Error: No recent image found to save and no valid file_path provided."
        except Exception as e:
            return f"Error fetching image from database: {e}"
        
    # Check if the content is base64 encoded (often sent as text files by the agent)
    import base64
    try:
        content_str = file_content.decode('utf-8').strip()
        if content_str.startswith('data:'):
            _, b64_data = content_str.split(',', 1)
            file_content = base64.b64decode(b64_data)
        else:
            decoded = base64.b64decode(content_str)
            if decoded.startswith(b'\xff\xd8\xff') or decoded.startswith(b'\x89PNG\r\n\x1a\n') or \
               decoded.startswith(b'%PDF-') or decoded.startswith(b'GIF87a') or decoded.startswith(b'GIF89a') or \
               (decoded.startswith(b'RIFF') and b'WEBP' in decoded[:16]) or \
               (b'ftyp' in decoded[:12]):
                file_content = decoded
    except Exception:
        pass

    file_hash = hashlib.sha256(file_content).hexdigest()
    
    # Try to determine extension from magic bytes
    ext = ""
    if file_content.startswith(b'\xff\xd8\xff'):
        ext = '.jpg'
    elif file_content.startswith(b'\x89PNG\r\n\x1a\n'):
        ext = '.png'
    elif file_content.startswith(b'%PDF-'):
        ext = '.pdf'
    elif file_content.startswith(b'GIF87a') or file_content.startswith(b'GIF89a'):
        ext = '.gif'
    elif file_content.startswith(b'RIFF') and b'WEBP' in file_content[:16]:
        ext = '.webp'
    elif b'ftypheic' in file_content[:16] or b'ftypheix' in file_content[:16]:
        ext = '.heic'
    elif b'ftyp' in file_content[:16]:
        ext = '.mp4' # fallback for other quicktime/mp4 containers like mov/mp4
    
    # Fallback to file name extension if not recognized
    if not ext:
        _, ext = os.path.splitext(file_path)
        
    hashed_filename = f"{file_hash}{ext}"
    
    dest_dir = os.path.join(os.getcwd(), 'bin', 'docs')
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, hashed_filename)
    
    try:
        with open(dest_path, 'wb') as f:
            f.write(file_content)
    except Exception as e:
        return f"Error saving file to {dest_path}: {e}"
    
    # Save to DB
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO extracted_documents (file_hash, file_name, category, extracted_data, metadata)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            file_hash, 
            hashed_filename, 
            category, 
            json.dumps(extracted_data) if extracted_data is not None else '{}', 
            json.dumps(additional_metadata or {})
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        return f"Error saving to database: {e}"
    
    return f"Document saved successfully as {hashed_filename} with hash {file_hash}."
