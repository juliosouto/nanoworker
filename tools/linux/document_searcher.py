import json
from database import get_db

def search_documents_data_in_database(query: str = None, limit: int = 10) -> dict:
    """
    Searches for extracted data from documents in the database. Use filters only if explicitly requested by user.
    MANDATORY: LLM must always return all keys-values in extracted_data and metadata fields, one pair per line (separated by \n).
    Example:
        McDonald's:
        2x Ttu1Car PrCP (27.45 each)
        Subtotal: 54.90
        Total: 54.90
        Paid with
        American Express: **** **** **** 3942
        54.90

    Args:
        query (str, optional): General search term (searches in file name, category, extracted data, and metadata).
        category (str, optional): Specific category to filter by (e.g., 'invoice', 'receipt', 'contract').
        start_date (str, optional): Start date in 'YYYY-MM-DD' format.
        end_date (str, optional): End date in 'YYYY-MM-DD' format.
        advanced_filters (dict, optional): Dictionary with exact keys and values to search within the extracted data. E.g., {"cnpj": "123456"}.
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

        # print('\n***************************************************')
        # print("DB PATH:", conn.execute("PRAGMA database_list").fetchall())
        # print("SQL:", sql)
        # print("PARAMS:", params)
        # print("ROWS:", list(rows))
        # print('***************************************************\n')
        
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
            
        return {"status": "success", "count": len(results), "data": results}
        
    except Exception as e:
        return {"status": "error", "message": f"Error searching documents: {str(e)}"}
