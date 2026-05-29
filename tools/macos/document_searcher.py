import json
from database import get_db
from utils.message_utils import format_document_search_results

def search_documents_data_in_database(query: str = None, limit: int = 10) -> dict:
    """
    Searches for extracted data from documents in the database.
    
    Args:
        query (str, optional): General search term (searches in file name, category, extracted data, and metadata).
        limit (int, optional): Limit of returned results (default 10).
        
    Returns:
        dict: A dictionary containing the search results or an error message.
    """

    try:
        if isinstance(query, str):
            query = query.strip()
            if query.lower() in ('none', 'null', '', '*'):
                query = None
            else:
                query = query.replace('*', '%')
            
        conn = get_db()
        cursor = conn.cursor()
        
        sql = "SELECT id, file_hash, file_name, category, extracted_data, metadata, created_at FROM extracted_documents WHERE 1=1"
        params = []
        
        if query:
            sql += " AND (file_name LIKE ? OR category LIKE ? OR extracted_data LIKE ? OR metadata LIKE ?)"
            like_query = f"%{query}%"
            params.extend([like_query, like_query, like_query, like_query])
            
        sql += " ORDER BY created_at DESC"
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        conn.close()
        
        results = []
        for row in rows:
            extracted_data_str = row['extracted_data']
            metadata_str = row['metadata']
            
            try:
                extracted_data = json.loads(extracted_data_str) if extracted_data_str else {}
            except json.JSONDecodeError:
                extracted_data = {}
                
            try:
                metadata = json.loads(metadata_str) if metadata_str else {}
            except json.JSONDecodeError:
                metadata = {}
            
            results.append({
                "id": row['id'],
                "file_hash": row['file_hash'],
                "file_name": row['file_name'],
                "category": row['category'],
                "created_at": row['created_at'],
                "extracted_data": extracted_data,
                "metadata": metadata
            })

            if len(results) >= limit:
                break
                
        if not results:
            return {"status": "success", "message": "No documents found matching the criteria.", "data": []}
            
        formatted_data = format_document_search_results(results)
        return {"status": "success", "count": len(results), "data": formatted_data}
        
    except Exception as e:
        return {"status": "error", "message": f"Error searching documents: {str(e)}"}
