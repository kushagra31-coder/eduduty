import os
import psycopg

def apply_schema():
    # This URL should point to your Supabase Postgres database or local Docker instance
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
    
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
            
        print(f"Connecting to {db_url}...")
        conn = psycopg.connect(db_url, autocommit=True)
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
