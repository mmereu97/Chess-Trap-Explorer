import chess.pgn
import io
import sqlite3
import json
from typing import List, Tuple, Any

DB_PATH = "openings.db"

def create_database_table(db_path: str):
    """Creează tabelul pentru deschideri dacă nu există."""
    with sqlite3.connect(db_path) as conn:
        # Ștergem tabelul vechi pentru a asigura date proaspete la fiecare rulare
        conn.execute("DROP TABLE IF EXISTS openings")
        conn.execute("""
            CREATE TABLE openings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moves_json TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                eco_code TEXT NOT NULL,
                move_count INTEGER NOT NULL
            )
        """)
        # Creăm un index pentru a face căutările ultra-rapide
        conn.execute("CREATE INDEX idx_move_count ON openings (move_count)")
        conn.commit()
    print("Database table 'openings' created successfully.")

def parse_and_insert(file_path: str, db_path: str):
    """Parsează eco.pgn și inserează datele într-o bază de date SQLite."""
    print(f"Starting to parse {file_path} and inserting into {db_path}...")
    
    batch_data: List[Tuple[str, str, str, int]] = []
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as pgn_file:
        while True:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break

            eco = game.headers.get("ECO", "N/A")
            opening = game.headers.get("Opening", "Unknown")
            variation = game.headers.get("Variation", None)
            
            full_name = opening
            if variation and opening.lower() not in variation.lower():
                full_name = f"{opening}: {variation}"
            elif variation:
                full_name = variation
            
            # --- AICI ESTE CORECȚIA CRUCIALĂ ---
            # Nu mai folosim board.san(move). În schimb, luăm SAN-ul direct
            # din nodurile jocului, care este mai robust pentru fișiere PGN
            # non-standard ca acesta.
            san_moves = []
            node = game
            while not node.is_end():
                next_node = node.variation(0)
                san_moves.append(node.board().san(next_node.move))
                node = next_node
            # ------------------------------------
                
            if not san_moves:
                continue

            moves_json = json.dumps(san_moves)
            move_count = len(san_moves)
            
            batch_data.append((moves_json, full_name, eco, move_count))

    if batch_data:
        # Folosim un set pentru a elimina duplicatele de secvențe de mutări
        # care ar putea avea nume diferite (ex. o linie principală și o variație cu același nume)
        # Păstrăm prima apariție, care este de obicei cea mai generală.
        unique_batch_data = {}
        for item in batch_data:
            moves_json = item[0]
            if moves_json not in unique_batch_data:
                unique_batch_data[moves_json] = item

        final_batch = list(unique_batch_data.values())

        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT INTO openings (moves_json, name, eco_code, move_count) VALUES (?, ?, ?, ?)",
                final_batch
            )
            conn.commit()
            print(f"Inserted {len(final_batch)} unique opening lines into the database.")

if __name__ == "__main__":
    input_pgn_path = "eco.pgn"
    
    create_database_table(DB_PATH)
    parse_and_insert(input_pgn_path, DB_PATH)
    print("Opening book database has been successfully built.")