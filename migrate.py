import sqlite3
import json

DB_PATH = "chess_traps.db"

def add_trap_type_column():
    """Adaugă coloana 'trap_type' la tabela 'queen_traps' dacă nu există."""
    print("Checking for 'trap_type' column in 'queen_traps' table...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Verificăm dacă coloana există deja pentru a putea rula scriptul de mai multe ori
            cursor.execute("PRAGMA table_info(queen_traps)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if 'trap_type' not in columns:
                print("Column 'trap_type' not found. Adding it...")
                # Adăugăm noua coloană. NOT NULL și DEFAULT sunt importante.
                cursor.execute("ALTER TABLE queen_traps ADD COLUMN trap_type TEXT NOT NULL DEFAULT 'QueenHunter'")
                conn.commit()
                print("✅ Column 'trap_type' added successfully.")
            else:
                print("✅ Column 'trap_type' already exists. No changes needed.")

    except sqlite3.Error as e:
        print(f"❌ ERROR: Could not alter table 'queen_traps': {e}")
        print("    If the table does not exist, run the main application first to create it.")

def update_existing_custom_traps():
    """
    Parcurge capcanele custom existente și setează 'trap_type' la 'Checkmate'
    dacă ultima mutare conține '#'.
    """
    print("\nUpdating trap types for existing custom traps...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Asigurăm că sqlite poate folosi funcții JSON (pentru versiuni mai vechi)
            conn.enable_load_extension(True)
            try:
                # Pe Windows, extensia poate avea un alt nume
                conn.load_extension("json1")
            except sqlite3.OperationalError:
                try:
                    # Pe Linux/macOS
                    conn.load_extension("libsqlite3-json1.so")
                except Exception as e:
                    print(f"    [WARNING] Could not load JSON1 extension: {e}. Update might be slower.")
            conn.enable_load_extension(False)

            cursor = conn.cursor()
            
            # Selectăm toate capcanele din tabela 'queen_traps'
            cursor.execute("SELECT id, moves FROM queen_traps")
            all_custom_traps = cursor.fetchall()
            
            updates_to_make = []
            for trap_id, moves_json in all_custom_traps:
                try:
                    moves = json.loads(moves_json)
                    if moves and moves[-1].endswith('#'):
                        updates_to_make.append((trap_id,))
                except (json.JSONDecodeError, IndexError):
                    continue
            
            if updates_to_make:
                print(f"Found {len(updates_to_make)} custom checkmate traps to update.")
                # Facem update la toate deodată
                cursor.executemany("UPDATE queen_traps SET trap_type = 'Checkmate' WHERE id = ?", updates_to_make)
                conn.commit()
                print(f"✅ Successfully updated {len(updates_to_make)} traps.")
            else:
                print("✅ No checkmate traps found in custom table. No updates needed.")

    except sqlite3.Error as e:
        print(f"❌ ERROR: Could not update trap types: {e}")

if __name__ == "__main__":
    print("--- Starting Database Migration Script ---")
    add_trap_type_column()
    update_existing_custom_traps()
    print("\n--- Migration Complete! ---")
    print("You can now run the main application with the updated code.")
