import psycopg2
import configparser

# --- CONFIGURARE ---
DB_NAME = "chess_trap_db"
# -----------------

def get_connection(dbname=None):
    """Stabilește o conexiune la PostgreSQL."""
    try:
        config = configparser.ConfigParser()
        config.read('config.ini')
        conn_details = config['postgresql']
        if dbname:
            conn_details['dbname'] = dbname
        conn = psycopg2.connect(**conn_details)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"❌ FATAL: Nu m-am putut conecta la PostgreSQL. Eroare: {e}")
        return None

def main():
    """Funcția principală care orchestrează reconstrucția completă (cu index de culoare)."""
    print("--- Începe scriptul de reconstrucție a bazei de date (Arhitectura Finală V3) ---")

    # 1. Conectare la serverul PostgreSQL și recrearea bazei de date
    print(f"\n[Pasul 1/3] Recrearea bazei de date '{DB_NAME}'...")
    conn = get_connection(dbname='postgres')
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute(f"DROP DATABASE IF EXISTS {DB_NAME};")
        cursor.execute(f"CREATE DATABASE {DB_NAME};")
        print(f"✅ Baza de date '{DB_NAME}' a fost recreată cu succes.")
    except Exception as e:
        print(f"❌ EROARE la recrearea bazei de date: {e}")
        return
    finally:
        cursor.close()
        conn.close()

    # 2. Conectare la noua bază de date și crearea structurii
    print(f"\n[Pasul 2/3] Crearea structurii de tabele în '{DB_NAME}'...")
    conn = get_connection(dbname=DB_NAME)
    if not conn: return
    cursor = conn.cursor()
    
    try:
        print("  - Crearea tabelei 'traps'...")
        cursor.execute("""
            CREATE TABLE traps (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                moves TEXT NOT NULL,
                color INTEGER NOT NULL,
                moves_hash VARCHAR(64)
            );""")
        cursor.execute("CREATE UNIQUE INDEX traps_color_hash_unique_idx ON traps (color, moves_hash);")
        cursor.execute("CREATE INDEX idx_traps_on_id ON traps (id);")

        print("  - Crearea tabelei 'position_index' (pentru date brute)...")
        cursor.execute("""
            CREATE TABLE position_index (
                shredder_fen VARCHAR(90) NOT NULL,
                trap_id INTEGER NOT NULL,
                move_index SMALLINT NOT NULL
            );
            """)
        cursor.execute("CREATE INDEX idx_pos_index_on_fen ON position_index (shredder_fen);")
        
        print("  - Crearea tabelei 'move_suggestions_index' (pentru viteză în joc)...")
        cursor.execute("""
            CREATE TABLE move_suggestions_index (
                shredder_fen VARCHAR(90) NOT NULL,
                suggested_move_san VARCHAR(10) NOT NULL,
                color INTEGER NOT NULL,
                trap_count INTEGER NOT NULL,
                example_trap_id INTEGER NOT NULL,
                PRIMARY KEY (shredder_fen, suggested_move_san, color)
            );
        """)
        
        print("  - Crearea tabelei 'first_move_suggestions' (pentru viteza la start)...")
        cursor.execute("""
            CREATE TABLE first_move_suggestions (
                first_move_san VARCHAR(10) NOT NULL,
                color INTEGER NOT NULL,
                trap_count INTEGER NOT NULL,
                example_trap_line TEXT NOT NULL,
                PRIMARY KEY (color, first_move_san)
            );
        """)
        
        print("✅ Structura de tabele a fost creată cu succes.")

    except Exception as e:
        print(f"❌ EROARE la crearea structurii de tabele: {e}")
        return
    finally:
        cursor.close()
        conn.close()

    print("\n[Pasul 3/3] Baza de date este goală și pregătită.")
    print("\n--- RECONSTRUCȚIE COMPLETĂ ---")
    print("Următorul pas: Modificați codul Python și rulați importul.")


if __name__ == "__main__":
    main()