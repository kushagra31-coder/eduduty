import os
import psycopg2

def apply_schema():
    # This URL should point to your Supabase Postgres database or local Docker instance
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
    
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
    
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
            
        print(f"Connecting to {db_url}...")
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Applying schema...")
        cursor.execute(schema_sql)
        print("Schema applied successfully!")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error applying schema: {e}")

if __name__ == "__main__":
    apply_schema()
