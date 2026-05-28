import json
from database import get_db

def search_documents_data_in_database(
    query: str = None, 
    category: str = None, 
    start_date: str = None, 
    end_date: str = None, 
    advanced_filters: dict = None,
    limit: int = 10
) -> dict:
    """
    Searches for extracted data from documents in the database. Use filters only if explicitly requested by user.
    
    Database Schema for 'extracted_documents':
    - id (INTEGER): Primary key
    - file_hash (TEXT): Hash of the file content
    - file_name (TEXT): Name of the file
    - category (TEXT): Category of the document (e.g., 'invoice', 'receipt', 'contract')
    - extracted_data (TEXT): JSON string containing the data extracted from the document
    - metadata (TEXT): JSON string containing additional metadata
    - created_at (TIMESTAMP): Date and time of insertion
    
    Args:
        query (str, optional): General search term (searches in file name, category, extracted data, and metadata).
        category (str, optional): Specific category to filter by (e.g., 'invoice', 'receipt', 'contract').
        start_date (str, optional): Start date in 'YYYY-MM-DD' format.
        end_date (str, optional): End date in 'YYYY-MM-DD' format.
        advanced_filters (dict, optional): Dictionary with exact keys and values to search within the extracted data. E.g., {"cnpj": "123456"}.
        limit (int, optional): Limit of returned results (default 10).
        
    Returns:
        dict: A dictionary containing the search results or an error message.

    IMPORTANT LLM INSTRUCTION: When returning results to the user, DO NOT summarize or omit fields. If the user asks for complete or detailed data, you MUST list every single key-value pair, item, and price found in 'extracted_data' and 'metadata' without shortening the list. Format the results in a clear and organized manner.
    """
    try:
        if isinstance(query, str):
            query = query.strip()
            if query.lower() in ('none', 'null', '', '*'):
                query = None
            else:
                query = query.replace('*', '%')
        if isinstance(category, str) and category.lower().strip() in ('none', 'null', '', '*'):
            category = None
        if isinstance(start_date, str) and start_date.lower().strip() in ('none', 'null', ''):
            start_date = None
        if isinstance(end_date, str) and end_date.lower().strip() in ('none', 'null', ''):
            end_date = None
            
        conn = get_db()
        cursor = conn.cursor()
        
        sql = "SELECT id, file_hash, file_name, category, extracted_data, metadata, created_at FROM extracted_documents WHERE 1=1"
        params = []
        
        if category:
            categories = [c.strip() for c in category.split(',')]
            if len(categories) == 1:
                sql += " AND category = ?"
                params.append(categories[0])
            else:
                placeholders = ', '.join(['?'] * len(categories))
                sql += f" AND category IN ({placeholders})"
                params.extend(categories)
            
        if start_date:
            sql += " AND created_at >= ?"
            params.append(f"{start_date} 00:00:00")
            
        if end_date:
            sql += " AND created_at <= ?"
            params.append(f"{end_date} 23:59:59")
            
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
            
            # Advanced filter done via Python to ensure exact match inside the extracted JSON
            include_row = True
            if advanced_filters and isinstance(advanced_filters, dict):
                for k, v in advanced_filters.items():
                    val_ext = str(extracted_data.get(k, "")).lower().strip()
                    val_meta = str(metadata.get(k, "")).lower().strip()
                    val_search = str(v).lower().strip()
                    
                    if val_search not in val_ext and val_search not in val_meta:
                        include_row = False
                        break
                        
            if include_row:
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
