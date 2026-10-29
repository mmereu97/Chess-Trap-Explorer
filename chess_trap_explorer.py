import configparser # Adaugă la începutul fișierului
import psycopg2   # Adaugă la începutul fișierului
import re
import io
import pygame
import chess
import chess.pgn
import sqlite3
import json
import os
import pyperclip
import pygame_textinput
import time
import pickle
from psycopg2.extras import RealDictCursor
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Protocol, Any
from pathlib import Path
from collections import defaultdict  # <--- ADAUGĂ ACEASTĂ LINIE AICI
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from functools import partial


# Import tkinter with error handling
try:
    from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QPushButton, 
                                   QLabel, QLineEdit, QCheckBox, QProgressBar, 
                                   QMessageBox, QFileDialog, QVBoxLayout, 
                                   QHBoxLayout, QGroupBox, QFrame, QScrollArea,
                                   QSizePolicy)
    from PySide6.QtCore import Qt, QSize
    QT_AVAILABLE = True
    print("[DEBUG INIT] PySide6 (Qt) imported successfully.")
except ImportError:
    QT_AVAILABLE = False
    print("[DEBUG INIT] PySide6 (Qt) not available - import functionality will be limited.")


# --- NOUA CONFIGURAȚIE PENTRU 720p (1280x720) ---
@dataclass
class UIConfig: # Numește-o direct UIConfig pentru a fi folosită
    """UI configuration constants for 720p resolution with history panel."""
    # --- Rezoluția totală ---
    WIDTH: int = 1280
    HEIGHT: int = 720
    
    # --- Dimensiuni Panouri (scalate cu ~1.5 și rotunjite) ---
    BUTTONS_WIDTH: int = 200
    SUGGESTIONS_WIDTH: int = 340
    
    # --- Dimensiuni Tablă și Panou Istoric ---
    BOARD_SIZE: int = 576
    SQUARE_SIZE: int = BOARD_SIZE // 8
    
    # --- Margini ---
    TOP_MARGIN: int = 40
    LEFT_MARGIN: int = BUTTONS_WIDTH + 40
    
    # --- Culori (rămân la fel) ---
    LIGHT_SQUARE: Tuple[int, int, int] = (240, 217, 181)
    DARK_SQUARE: Tuple[int, int, int] = (181, 136, 99)
    PANEL_COLOR: Tuple[int, int, int] = (50, 50, 50)
    BUTTON_COLOR: Tuple[int, int, int] = (70, 70, 70)
    BUTTON_HOVER_COLOR: Tuple[int, int, int] = (90, 90, 90)
    TEXT_COLOR: Tuple[int, int, int] = (255, 255, 255)
    BORDER_COLOR: Tuple[int, int, int] = (100, 100, 100)
    HIGHLIGHT_RED: Tuple[int, int, int, int] = (255, 0, 0, 120)
    HIGHLIGHT_GREEN: Tuple[int, int, int, int] = (0, 255, 0, 120)

    # NOU: Culori specifice pentru sugestii
    SUGGESTION_BLUE: Tuple[int, int, int] = (60, 60, 100) # Pentru checkmate
    SUGGESTION_PURPLE: Tuple[int, int, int] = (90, 60, 100) # Pentru queen hunter

# --- NOU: Adaugă această clasă după `ChessTrap` ---
@dataclass
class QueenTrap:
    """Represents a custom recorded trap (mat, queen hunt, etc.)."""
    name: str
    trap_type: str 
    moves: List[str]
    color: chess.Color
    capture_square: chess.Square
    created_at: Optional[str] = None # <-- ADAUGĂ SAU VERIFICĂ ACEASTĂ LINIE
    id: Optional[int] = None

@dataclass
class ChessTrap:
    """Represents a chess trap."""
    name: str
    moves: List[str]
    color: chess.Color
    id: Optional[int] = None

@dataclass
class MoveSuggestion:
    """Represents a suggestion for a next move, aggregated from multiple traps."""
    suggested_move: str
    trap_count: int
    example_trap_line: List[str]
    trap_type: str  # NOU: va fi 'checkmate' sau 'queen_hunter'

@dataclass
class GameState:
    """Represents the current state of the chess game."""
    board: chess.Board
    current_player: chess.Color
    is_recording: bool = False
    move_history: List[str] = field(default_factory=list)
    recording_history: List[str] = field(default_factory=list)
    selected_square: Optional[chess.Square] = None
    dragging_piece: Optional[chess.Piece] = None
    drag_pos: Optional[Tuple[int, int]] = None
    highlighted_squares: Optional[Tuple[chess.Square, chess.Square]] = None
    highlight_color: Optional[Tuple[int, int, int, int]] = None
    active_trap_line: Optional[List[str]] = None
    trap_success_message: Optional[str] = None # NOU: Mesaj de succes

@dataclass
class OpeningInfo:
    """Informații despre o deschidere, citite din baza de date."""
    name: str
    eco_code: str

# Repository Layer

def process_pgn_games_chunk(game_string_list: List[str], max_moves: int, checkmate_only: bool) -> Tuple[List['ChessTrap'], List['ChessTrap']]:
    """
    Process a chunk of PGN games. This function runs in a separate process.
    
    Arguments:
        game_string_list (List[str]): A list of PGN strings, each representing a game.
        max_moves (int): The maximum number of semi-moves a trap can have.
        checkmate_only (bool): Whether to import only checkmating lines.
        
    Returns:
        Tuple[List[ChessTrap], List[ChessTrap]]: Two lists of traps, one for white and one for black.
    """
    
    # Imports needed within the worker process (leave them as they are, they are correct here)
    import chess.pgn
    import io
    import json
    import hashlib

    white_traps = []
    black_traps = []
    
    # --- THIS IS THE CORRECTED LINE ---
    for game_string in game_string_list: # Now iterates through the correctly named argument
        try:
            game = chess.pgn.read_game(io.StringIO(game_string))
            if game is None:
                continue
                
            moves = list(game.mainline_moves())
            if not (4 <= len(moves) <= max_moves):
                continue
                
            board = chess.Board()
            san_moves = []
            for move in moves:
                san_moves.append(board.san(move))
                board.push(move)
                
            if not board.is_checkmate() or not san_moves[-1].endswith('#'):
                continue
                
            num_moves = len(san_moves)
            trap_color = chess.WHITE if (num_moves % 2 != 0) else chess.BLACK
                
            trap_name = game.headers.get("Event", f"Imported Trap") + " (Checkmate)"
                
            # ChessTrap is now globally defined and visible here
            trap = ChessTrap(name=trap_name, moves=san_moves, color=trap_color)
                
            if trap_color == chess.WHITE:
                white_traps.append(trap)
            else:
                black_traps.append(trap)
                    
        except Exception:
            # It's better to ignore games with parsing errors for very large files
            continue
        
    return white_traps, black_traps

def audit_database_for_checkmates(db_path="chess_traps.db"):
    """
    Reads all traps from the database and reports any trap where the
    last move in the sequence does not end with a '#' character.
    """
    print("\n--- STARTING FAST DATABASE AUDIT (checking for '#') ---")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT id, name, moves FROM traps")
        all_traps = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"[AUDIT ERROR] Could not read from database: {e}")
        return

    failed_traps = 0
    total_traps = len(all_traps)
    print(f"Analyzing {total_traps} traps...")

    for trap_id, name, moves_json in all_traps:
        try:
            moves = json.loads(moves_json)
            
            # Verificăm dacă lista de mutări nu este goală și dacă ultima mutare se termină cu #
            if not moves or not moves[-1].endswith('#'):
                failed_traps += 1
                print(f"[AUDIT FAILED] Trap '{name}' (ID: {trap_id}) does not end with '#'. Last move: {moves[-1] if moves else 'N/A'}")
        
        except Exception as e:
            failed_traps += 1
            print(f"[AUDIT FAILED] Could not parse moves for trap '{name}' (ID: {trap_id}). Error: {e}")

    print("\n--- AUDIT COMPLETE ---")
    if failed_traps == 0:
        print("✅ All traps in the database correctly end with the checkmate symbol '#'.")
    else:
        print(f"❌ Found {failed_traps} out of {total_traps} traps that are not valid checkmate lines (missing '#').")
    print("------------------------\n")

def audit_specific_line(line_to_check: List[str], db_path="chess_traps.db"):
    """
    Finds all traps that start with a specific sequence of moves and
    prints their continuations.
    """
    sequence_str = " ".join(line_to_check)
    print(f"\n--- AUDITING SPECIFIC LINE: {sequence_str} ---")
    
    try:
        conn = sqlite3.connect(db_path)
        # Folosim LIKE pentru a găsi potriviri la începutul string-ului JSON
        # Notă: Asta poate fi lent pe baze de date foarte mari, dar e perfect pentru audit
        json_prefix = json.dumps(line_to_check)[:-1] # Ex: '["e4", "e5"]' -> '["e4", "e5"'
        
        cursor = conn.execute("SELECT id, name, moves FROM traps WHERE moves LIKE ?", (f"{json_prefix}%",))
        matching_traps = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"[AUDIT ERROR] Could not read from database: {e}")
        return

    print(f"Found {len(matching_traps)} traps starting with this sequence.")
    if not matching_traps:
        print("------------------------------------------\n")
        return

    for trap_id, name, moves_json in matching_traps:
        full_line = json.loads(moves_json)
        
        # Extragem continuarea
        continuation = full_line[len(line_to_check):]
        
        print(f"\n> Trap: '{name}' (ID: {trap_id})")
        print(f"  - Full Length: {len(full_line)} moves")
        if continuation:
            print(f"  - CONTINUATION: {' '.join(continuation)}")
        else:
            print("  - CONTINUATION: NONE. This trap ends here.")
            
    print("\n--- AUDIT COMPLETE FOR SPECIFIC LINE ---")

# --- Noul dicționar cu "amprentele" sistemelor ---
SYSTEM_FINGERPRINTS: Dict[str, Any] = {
    chess.WHITE: {
        "London System": {
            "pieces": {chess.PAWN: [chess.D4], chess.BISHOP: [chess.F4], chess.KNIGHT: [chess.F3]},
            "description": "London System"
        },
        "King's Indian Attack": {
            "pieces": {chess.KNIGHT: [chess.F3], chess.PAWN: [chess.G3, chess.D3], chess.BISHOP: [chess.G2]},
            "description": "King's Indian Attack"
        },
        "Colle System": {
            "pieces": {chess.PAWN: [chess.D4, chess.E3], chess.KNIGHT: [chess.F3]},
            "description": "Colle System"
        },
        "Réti Opening": {
            "pieces": {chess.KNIGHT: [chess.F3], chess.PAWN: [chess.C4, chess.G3]},
            "description": "Réti Opening"
        }
    },
    chess.BLACK: {
        "King's Indian Defense": {
            "pieces": {chess.KNIGHT: [chess.F6], chess.PAWN: [chess.G6, chess.D6], chess.BISHOP: [chess.G7]},
            "description": "King's Indian Defense"
        },
        "Grünfeld Defense": {
            "pieces": {chess.KNIGHT: [chess.F6], chess.PAWN: [chess.G6, chess.D5], chess.BISHOP: [chess.G7]},
            "description": "Grünfeld Defense"
        },
        "Modern Defense": {
            "pieces": {chess.PAWN: [chess.G6], chess.BISHOP: [chess.G7]},
            "description": "Modern Defense Setup"
        },
        "Dutch Defense": {
            "pieces": {chess.PAWN: [chess.F5]},
            "description": "Dutch Defense"
        }
    }
}




class TrapRepository:
    """Repository for managing chess traps in PostgreSQL database."""

    def __init__(self, db_path: str = "chess_traps.db"):
        self._initialize_database()

    def _get_db_connection(self):
        try:
            config = configparser.ConfigParser()
            config.read('config.ini')
            conn_details = config['postgresql']
            conn = psycopg2.connect(
                host=conn_details['host'],
                port=conn_details['port'],
                dbname=conn_details['dbname'],
                user=conn_details['user'],
                password=conn_details['password']
            )
            return conn
        except (Exception, psycopg2.Error) as error:
            print(f"[DB ERROR] Could not connect to PostgreSQL: {error}")
            return None

    def _initialize_database(self) -> None:
        print("[DB MIGRATE] Checking PostgreSQL database schema...")
        conn = self._get_db_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS traps (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        moves TEXT NOT NULL,
                        color INTEGER NOT NULL,
                        moves_hash VARCHAR(64),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );""")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS traps_color_hash_unique_idx ON traps (color, moves_hash);")
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS queen_traps (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        trap_type TEXT NOT NULL,
                        moves TEXT NOT NULL,
                        color INTEGER NOT NULL,
                        capture_square INTEGER NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );""")

                # Această secțiune este sigură. "IF NOT EXISTS" va preveni orice eroare
                # dacă tabela deja există (ceea ce este cazul acum).
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS position_index (
                        shredder_fen VARCHAR(90) NOT NULL,
                        trap_id INTEGER NOT NULL,
                        move_index SMALLINT NOT NULL,
                        color INTEGER NOT NULL
                    ) PARTITION BY LIST (substring(shredder_fen from 1 for 3));
                    """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_fen_on_position_index ON position_index (shredder_fen);")
                
                conn.commit()
            print("[DB MIGRATE] PostgreSQL Schema is up to date.")
        except psycopg2.Error as e:
            print(f"[DB MIGRATE ERROR] Failed to initialize tables: {e}")
        finally:
            if conn: conn.close()
            
    def bulk_import_and_index_traps(self, traps: List[ChessTrap]) -> Tuple[int, int, int]:
        """
        [ARHITECTURA FINALĂ V3.1 - COMBINAȚIE STABILĂ]
        """
        if not traps: return 0, 0, 0
        conn = self._get_db_connection()
        if not conn: return 0, 0, 0
        
        import hashlib
        import logging
        import math
        import psycopg2.extras
        
        newly_inserted_traps = []
        
        try:
            with conn.cursor() as cursor:
                # PASUL 1: Inserarea capcanelor (neschimbat)
                print(f"[DB IMPORT] Pregătirea a {len(traps)} capcane pentru inserare...")
                temp_table_name = "import_buffer"
                cursor.execute(f"CREATE TEMP TABLE {temp_table_name} (name TEXT, moves TEXT, color INT, moves_hash VARCHAR(64)) ON COMMIT DROP;")
                sio = io.StringIO()
                for trap in traps:
                    moves_json = json.dumps(trap.moves)
                    moves_hash = hashlib.sha256(moves_json.encode('utf-8')).hexdigest()
                    clean_name = trap.name.replace('\\', '\\\\').replace('\t', ' ').replace('\n', ' ').replace('\r', '')
                    sio.write(f"{clean_name}\t{moves_json}\t{int(trap.color)}\t{moves_hash}\n")
                sio.seek(0)
                cursor.copy_expert(f"COPY {temp_table_name} FROM STDIN", sio)
                cursor.execute(f"""
                    INSERT INTO traps (name, moves, color, moves_hash)
                    SELECT name, moves, color, moves_hash FROM {temp_table_name}
                    ON CONFLICT (color, moves_hash) DO NOTHING
                    RETURNING id, moves, color;
                """)
                newly_inserted_traps = cursor.fetchall()
                inserted_count = len(newly_inserted_traps)
                if inserted_count == 0:
                    conn.commit()
                    logging.info("[DB IMPORT] Nu au fost găsite capcane noi.")
                    return 0, 0, 0
                logging.info(f"[DB IMPORT] S-au inserat {inserted_count} capcane noi.")
                conn.commit()

                # PASUL 2: Popularea indexului brut (neschimbat)
                logging.info(f"[DB INDEX BRUT] Începe indexarea celor {inserted_count} capcane noi (în loturi)...")
                BATCH_SIZE = 50000
                total_batches = math.ceil(inserted_count / BATCH_SIZE)
                board = chess.Board()
                traps_processed_so_far = 0
                for i in range(total_batches):
                    batch_start_time = time.time()
                    start_index = i * BATCH_SIZE
                    end_index = start_index + BATCH_SIZE
                    current_batch = newly_inserted_traps[start_index:end_index]
                    
                    index_sio = io.StringIO()
                    for trap_id, moves_json, _ in current_batch:
                        moves = json.loads(moves_json)
                        board.reset()
                        for move_idx, move_san in enumerate(moves[:-1]):
                            try:
                                move = board.parse_san(move_san.replace('#','').replace('+',''))
                                board.push(move)
                                fen = board.fen().split(' ')[0]
                                index_sio.write(f"{fen}\t{trap_id}\t{move_idx}\n")
                            except ValueError:
                                continue
                    
                    index_sio.seek(0)
                    if index_sio.getvalue():
                        cursor.copy_expert("COPY position_index (shredder_fen, trap_id, move_index) FROM STDIN", index_sio)
                    conn.commit()
                    batch_end_time = time.time()
                    traps_processed_so_far += len(current_batch)
                    logging.info(
                        f"  -> Lotul {i + 1}/{total_batches} finalizat în {batch_end_time - batch_start_time:.2f}s. "
                        f"Total capcane indexate: {traps_processed_so_far}/{inserted_count}"
                    )
                logging.info("[DB INDEX BRUT] Indexarea brută a fost finalizată.")
                
        except Exception as e:
            logging.error(f"[DB IMPORT/INDEX ERROR] Eroare în faza de import brut: {e}", exc_info=True)
            if conn: conn.rollback()
            return 0, 0, 0
        finally:
            if conn and not conn.closed:
                pass

        try:
            with conn.cursor() as cursor:
                # PASUL 3: Actualizarea INCREMENTALĂ (cu logica veche, dar în buclă)
                logging.info("\n[DB INDEX SUGESTII] Începe actualizarea incrementală a indexului de sugestii (în loturi)...")
                
                cursor.execute("SELECT COUNT(*) FROM move_suggestions_index;")
                suggestions_before = cursor.fetchone()[0]
                logging.info(f"  STARE INIȚIALĂ: Indexul conține {suggestions_before:,} de sugestii unice.")

                new_trap_ids = [item[0] for item in newly_inserted_traps]
                SUGGESTION_BATCH_SIZE = 10000
                total_suggestion_batches = math.ceil(len(new_trap_ids) / SUGGESTION_BATCH_SIZE)
                total_suggestions_updated_this_session = 0

                for i in range(total_suggestion_batches):
                    batch_start_time = time.time()
                    start_index = i * SUGGESTION_BATCH_SIZE
                    end_index = start_index + SUGGESTION_BATCH_SIZE
                    current_batch_ids = new_trap_ids[start_index:end_index]

                    if not current_batch_ids:
                        continue
                    
                    # Ștergem și recreăm tabela temporară la fiecare lot
                    cursor.execute("DROP TABLE IF EXISTS new_trap_ids;")
                    cursor.execute("CREATE TEMP TABLE new_trap_ids (id INT PRIMARY KEY) ON COMMIT DROP;")
                    psycopg2.extras.execute_values(cursor, "INSERT INTO new_trap_ids (id) VALUES %s", [(tid,) for tid in current_batch_ids])

                    sql_upsert_query = """
                    WITH new_suggestions AS (
                        SELECT
                            pi.shredder_fen,
                            t.moves::json ->> (pi.move_index + 1) AS suggested_move,
                            t.color,
                            COUNT(*) AS new_count,
                            (array_agg(t.id))[1] AS example_id
                        FROM 
                            position_index pi
                        JOIN 
                            traps t ON pi.trap_id = t.id
                        WHERE
                            t.id IN (SELECT id FROM new_trap_ids)
                            AND json_array_length(t.moves::json) > (pi.move_index + 1)
                            AND (pi.move_index + 1) % 2 = (CASE WHEN t.color = 1 THEN 0 ELSE 1 END)
                        GROUP BY
                            pi.shredder_fen, suggested_move, t.color
                    )
                    INSERT INTO move_suggestions_index (shredder_fen, suggested_move_san, color, trap_count, example_trap_id)
                    SELECT shredder_fen, suggested_move, color, new_count, example_id FROM new_suggestions
                    ON CONFLICT (shredder_fen, suggested_move_san, color) 
                    DO UPDATE SET
                        trap_count = move_suggestions_index.trap_count + excluded.trap_count;
                    """
                    
                    # --- ACEASTA ESTE CORECȚIA FINALĂ, REVENIND LA METODA STABILĂ ---
                    cursor.execute(sql_upsert_query)
                    # -----------------------------------------------------------------
                    
                    count = cursor.rowcount
                    conn.commit()
                    batch_end_time = time.time()
                    total_suggestions_updated_this_session += count

                    logging.info(
                        f"  -> Lot de sugestii {i + 1}/{total_suggestion_batches} finalizat în {batch_end_time - batch_start_time:.2f}s. "
                        f"({count} sugestii afectate în acest lot)."
                    )
                
                cursor.execute("SELECT COUNT(*) FROM move_suggestions_index;")
                suggestions_after = cursor.fetchone()[0]
                newly_created_suggestions = suggestions_after - suggestions_before
                
                logging.info(f"✅ [DB INDEX SUGESTII] Actualizare finalizată!")
                logging.info(f"  - Total sugestii afectate (inserate/actualizate) în această sesiune: {total_suggestions_updated_this_session:,}")
                logging.info(f"  - Sugestii noi create (rânduri noi în index): {newly_created_suggestions:,}")
                logging.info(f"  - TOTAL SUGESTII ÎN INDEX: {suggestions_after:,}")

        except Exception as e:
            logging.error(f"[DB SUGGESTION BUILD ERROR] Eroare la actualizarea indexului de sugestii: {e}", exc_info=True)
            if conn: conn.rollback()
            return 0, 0, 0
        finally:
            if conn: conn.close()
            
        white_final = sum(1 for _, _, color in newly_inserted_traps if color == 1)
        black_final = sum(1 for _, _, color in newly_inserted_traps if color == 0)
        return inserted_count, white_final, black_final

    def get_batch_trap_moves(self, trap_ids: List[int]) -> Dict[int, List[str]]:
        """Gets moves for a batch of trap IDs efficiently."""
        if not trap_ids: return {}
        conn = self._get_db_connection()
        if not conn: return {}
        
        moves_map = {}
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, moves FROM traps WHERE id = ANY(%s)", (trap_ids,))
                for trap_id, moves_json in cursor.fetchall():
                    moves_map[trap_id] = json.loads(moves_json)
        finally:
            if conn: conn.close()
        
        return moves_map

    def get_all_first_moves(self, color: chess.Color) -> List[Tuple[str, int, str]]:
        """
        [VERSIUNE OPTIMIZATĂ] Citește sugestiile pre-calculate pentru prima mutare
        direct din tabela 'first_move_suggestions'.
        """
        conn = self._get_db_connection()
        if not conn: return []
        
        move_data = []
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT first_move_san, trap_count, example_trap_line
                    FROM first_move_suggestions
                    WHERE color = %s
                    ORDER BY trap_count DESC;
                    """,
                    (int(color),)
                )
                move_data = cursor.fetchall()
        except psycopg2.Error as e:
            print(f"[DB QUERY ERROR] Nu am putut citi sugestiile de start: {e}")
        finally:
            if conn: conn.close()
        return move_data

    def get_total_trap_count(self) -> int:
        """Get total number of traps in database."""
        conn = self._get_db_connection()
        if not conn: return 0
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM traps")
                return cursor.fetchone()[0]
        except psycopg2.Error:
            return 0
        finally:
            if conn:
                conn.close()

    def get_trap_count_for_color(self, color: chess.Color) -> int:
        """Gets the total number of traps for a specific color."""
        conn = self._get_db_connection()
        if not conn: return 0
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM traps WHERE color = %s", (int(color),))
                return cursor.fetchone()[0]
        except psycopg2.Error:
            return 0
        finally:
            if conn: conn.close()

    def clear_all_traps(self) -> int:
        """
        Deletes ALL traps from the 'traps' table and the 'position_index' table,
        and returns the number of deleted traps.
        """
        conn = self._get_db_connection()
        if not conn: return 0
        
        deleted_count = 0
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM traps")
                deleted_count = cursor.rowcount
                conn.commit()
        except psycopg2.Error as e:
            print(f"[DB CLEAR ERROR] {e}")
            conn.rollback()
        finally:
            if conn:
                conn.close()
        
        if deleted_count > 0:
            print(f"[DB CLEAR] Deleted {deleted_count} traps and their corresponding index entries.")
        return deleted_count

    def get_trap_counts_by_color(self) -> Tuple[int, int]:
        """Returns the number of traps for White and Black."""
        white_count, black_count = 0, 0
        conn = self._get_db_connection()
        if not conn: return (0, 0)
        
        try:
            with conn.cursor() as cursor:
                # Grupăm după culoare și numărăm intrările
                cursor.execute("SELECT color, COUNT(*) FROM traps GROUP BY color")
                for color, count in cursor.fetchall():
                    if color == 1:  # 1 este pentru Alb
                        white_count = count
                    else:  # 0 este pentru Negru
                        black_count = count
        except psycopg2.Error as e:
            print(f"[DB ERROR] Could not get trap counts: {e}")
        finally:
            if conn:
                conn.close()
        return white_count, black_count

    def iterate_all_traps(self, batch_size: int = 10000):
        """
        Yields traps from the database in batches using a server-side cursor
        to avoid loading पुलिस into memory at once.
        """
        conn = self._get_db_connection()
        if not conn:
            return

        # Folosim un cursor cu nume (server-side)
        cursor_name = "export_cursor"
        try:
            with conn.cursor(name=cursor_name) as cursor:
                cursor.itersize = batch_size # Cât să aducă de la server la fiecare fetch
                cursor.execute("SELECT name, moves, color FROM traps ORDER BY id")
                
                while True:
                    batch = cursor.fetchmany(batch_size)
                    if not batch:
                        break
                    
                    for name, moves_json, color in batch:
                        yield ChessTrap(
                            name=name,
                            moves=json.loads(moves_json),
                            color=bool(color)
                        )
        finally:
            if conn:
                conn.close()

class QueenTrapRepository:
    """Repository for managing queen-hunting traps in PostgreSQL database."""
    
    def __init__(self, db_path: str = "chess_traps.db"):
        # Inițializarea este deja făcută de TrapRepository, nu mai e nevoie aici
        pass

    def _get_db_connection(self):
        """Reutilizăm logica de conectare a clasei TrapRepository."""
        return TrapRepository(db_path="")._get_db_connection()

    def save_trap(self, trap: QueenTrap) -> int:
        """Save a queen trap to the PostgreSQL database and return its ID."""
        conn = self._get_db_connection()
        if not conn: return -1
        
        try:
            with conn.cursor() as cursor:
                # NOU: Verificare duplicat cu %s
                cursor.execute(
                    "SELECT id FROM queen_traps WHERE moves = %s AND color = %s",
                    (json.dumps(trap.moves), int(trap.color))
                )
                if cursor.fetchone():
                    print("[DB QUEEN] Duplicate queen trap found. Skipping save.")
                    return -1

                # NOU: Inserare cu %s și RETURNING id
                cursor.execute(
                    """INSERT INTO queen_traps 
                       (name, trap_type, moves, color, capture_square) 
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (trap.name, trap.trap_type, json.dumps(trap.moves), int(trap.color), trap.capture_square)
                )
                trap_id = cursor.fetchone()[0]
                conn.commit()
                return trap_id
        except psycopg2.Error as e:
            print(f"[DB QUEEN SAVE ERROR] {e}")
            return -1
        finally:
            if conn:
                conn.close()

    def get_all_traps(self) -> List[QueenTrap]:
        traps = []
        conn = self._get_db_connection()
        if not conn: return traps

        try:
            # NOU: RealDictCursor face codul mai curat
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id, name, trap_type, moves, color, capture_square, created_at FROM queen_traps")
                
                for row in cursor.fetchall():
                    traps.append(QueenTrap(
                        id=row['id'], 
                        name=row['name'], 
                        trap_type=row['trap_type'], 
                        moves=json.loads(row['moves']), 
                        color=bool(row['color']), 
                        capture_square=int(row['capture_square']),
                        created_at=str(row['created_at'])
                    ))
        except psycopg2.Error as e:
            print(f"[DB QUEEN ERROR] Could not read queen traps: {e}")
        finally:
            if conn:
                conn.close()
        return traps
            
    def delete_trap_by_id(self, trap_id: int) -> None:
        """Deletes a specific queen trap by its ID from PostgreSQL."""
        conn = self._get_db_connection()
        if not conn: return
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM queen_traps WHERE id = %s", (trap_id,))
                conn.commit()
        except psycopg2.Error as e:
            print(f"[DB QUEEN DELETE ERROR] {e}")
        finally:
            if conn:
                conn.close()

    def get_total_trap_count(self) -> int:
        """Get total number of custom traps from PostgreSQL."""
        conn = self._get_db_connection()
        if not conn: return 0
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM queen_traps")
                return cursor.fetchone()[0]
        except psycopg2.Error:
            return 0
        finally:
            if conn:
                conn.close()

    def delete_checkmate_traps(self) -> int:
        """Deletes all manually recorded checkmates from the queen_traps table in PostgreSQL."""
        conn = self._get_db_connection()
        if not conn: return 0
        
        deleted_count = 0
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM queen_traps WHERE trap_type = 'Checkmate'")
                deleted_count = cursor.rowcount
                conn.commit()
                print(f"[DB QUEEN] Deleted {deleted_count} custom checkmate traps.")
        except psycopg2.Error as e:
            print(f"[DB QUEEN DELETE ERROR] {e}")
        finally:
            if conn:
                conn.close()
        return deleted_count

    def clear_all_traps(self) -> int:
        """Deletes ALL traps from the 'queen_traps' table."""
        conn = self._get_db_connection()
        if not conn: return 0
        
        deleted_count = 0
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM queen_traps")
                deleted_count = cursor.rowcount
                conn.commit()
        except psycopg2.Error as e:
            print(f"[DB QUEEN CLEAR ERROR] {e}")
            conn.rollback()
        finally:
            if conn:
                conn.close()
        
        if deleted_count > 0:
            print(f"[DB QUEEN CLEAR] Deleted {deleted_count} custom traps.")
        return deleted_count

# Service Layer
class TrapService:
    """
    [ARHITECTURA FINALĂ]
    Service for managing trap logic and suggestions.
    Reads pre-calculated suggestions directly from the move_suggestions_index.
    """
    
    def __init__(self, repository: TrapRepository):
        self.repository = repository
        print("[TRAP SERVICE] Initialized in PRE-CALCULATED mode.")

    def get_aggregated_suggestions(self, game_state: GameState) -> Tuple[List[MoveSuggestion], int]:
        """
        [ARHITECTURA FINALĂ V2]
        Citește sugestiile pre-calculate pentru JUCĂTORUL CURENT.
        """
        if game_state.board.turn != game_state.current_player:
            return [], 0
        
        if not game_state.move_history:
            # Logica pentru începutul jocului rămâne la fel
            move_data = self.repository.get_all_first_moves(game_state.current_player)
            suggestions = []
            for move, count, example_moves_json in move_data:
                try:
                    example_line = json.loads(example_moves_json)
                    suggestions.append(MoveSuggestion(
                        suggested_move=move,
                        trap_count=count,
                        example_trap_line=example_line,
                        trap_type='checkmate'
                    ))
                except json.JSONDecodeError:
                    continue
            total_traps_for_color = self.repository.get_trap_count_for_color(game_state.current_player)
            return suggestions, total_traps_for_color

        shredder_fen = game_state.board.fen().split(' ')[0]
        suggestions = []
        total_matching_traps = 0
        conn = self.repository._get_db_connection()
        if not conn: return [], 0

        import time
        t0 = time.time()

        try:
            with conn.cursor() as cursor:
                # Interogare ultra-rapidă, care filtrează acum și după CULOARE
                sql_query = """
                    SELECT suggested_move_san, trap_count, example_trap_id 
                    FROM move_suggestions_index 
                    WHERE shredder_fen = %s AND color = %s -- FILTRUL CRITIC ADĂUGAT AICI
                    ORDER BY trap_count DESC;
                """
                cursor.execute(sql_query, (shredder_fen, int(game_state.current_player)))
                results = cursor.fetchall()

                if results:
                    example_trap_ids = [row[2] for row in results]
                    moves_map = self.repository.get_batch_trap_moves(example_trap_ids)
                    total_matching_traps = sum(row[1] for row in results)

                    for row in results:
                        example_id = row[2]
                        full_trap_line = moves_map.get(example_id, [])
                        continuation = full_trap_line[len(game_state.move_history):]
                        suggestions.append(MoveSuggestion(
                            suggested_move=row[0],
                            trap_count=row[1],
                            example_trap_line=continuation,
                            trap_type='checkmate'
                        ))
        except Exception as e:
            print(f"[DB ERROR] Eroare în interogarea de sugestii: {e}")
        finally:
            if conn: conn.close()

        t1 = time.time()
        print(f"[TIMING] Interogarea pre-calculată (cu filtru de culoare) a durat: {t1 - t0:.4f} secunde.")
        
        return suggestions, total_matching_traps

    # Metodele vechi nu mai sunt necesare în fluxul principal, dar le păstrăm
    def count_matching_traps(self, game_state: GameState) -> int:
        shredder_fen = game_state.board.fen().split(' ')[0]
        conn = self.repository._get_db_connection()
        if not conn: return 0
        count = 0
        try:
            with conn.cursor() as cursor:
                 cursor.execute(
                    "SELECT SUM(trap_count) FROM move_suggestions_index WHERE shredder_fen = %s;",
                    (shredder_fen,)
                )
                 result = cursor.fetchone()
                 if result and result[0]:
                     count = int(result[0])
        finally:
            if conn: conn.close()
        return count


class QueenTrapService:
    """
    Service for managing queen trap logic and suggestions with on-disk caching.
    Este o paralelă a lui TrapService, dar pentru tabela queen_traps.
    """
    CACHE_FILE_PATH = "queen_trap_index.cache"
    
    def __init__(self, repository: QueenTrapRepository):
        self.repository = repository
        print("[QUEEN TRAP SERVICE] Initializing...")
        start_time = time.time()
        
        self.all_traps = self.repository.get_all_traps()
        self.id_to_trap_map = {trap.id: trap for trap in self.all_traps}
        
        if not self._load_index_from_cache():
            print("[QUEEN TRAP SERVICE] Cache not found or invalid. Building new index...")
            self.position_index = self._create_position_index()
            self._save_index_to_cache()
        
        end_time = time.time()
        print(f"[QUEEN TRAP SERVICE] Initialization complete in {end_time - start_time:.4f} seconds.")
        if self.all_traps:
            trap_count_formatted = f"{len(self.all_traps):_}".replace("_", " ")
            position_count_formatted = f"{len(self.position_index):_}".replace("_", " ")
            print(f"                     Using index for {trap_count_formatted} queen traps across {position_count_formatted} unique positions.")

    def _load_index_from_cache(self) -> bool:
        if not os.path.exists(self.CACHE_FILE_PATH):
            return False
        try:
            with open(self.CACHE_FILE_PATH, 'rb') as f:
                cache_data = pickle.load(f)
            current_trap_count = len(self.all_traps)
            current_id_sum = sum(trap.id for trap in self.all_traps if trap.id is not None)
            if current_trap_count == cache_data.get('trap_count') and current_id_sum == cache_data.get('id_sum'):
                self.position_index = cache_data['index']
                print("[QUEEN TRAP SERVICE] Cache is valid and loaded.")
                return True
            return False
        except Exception as e:
            print(f"[QUEEN TRAP SERVICE] Cache load failed: {e}. Rebuilding.")
            return False

    def _save_index_to_cache(self) -> None:
        if not hasattr(self, 'position_index') or not self.position_index:
            return
        cache_data = {
            'trap_count': len(self.all_traps),
            'id_sum': sum(trap.id for trap in self.all_traps if trap.id is not None),
            'index': self.position_index
        }
        try:
            with open(self.CACHE_FILE_PATH, 'wb') as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        except IOError as e:
            print(f"[QUEEN TRAP SERVICE] [ERROR] Could not write cache file: {e}")

    def _create_position_index(self) -> Dict[str, List[Tuple[int, int]]]:
        index = defaultdict(list)
        for trap in self.all_traps:
            if trap.id is None: continue
            board = chess.Board()
            try:
                for i, move_san in enumerate(trap.moves):
                    clean_san = move_san.replace('#', '').replace('+', '')
                    move = board.parse_san(clean_san)
                    board.push(move)
                    positional_fen = board.shredder_fen()
                    index[positional_fen].append((trap.id, i))
            except ValueError as e:
                print(f"[QUEEN INDEX WARNING] Skipping trap ID {trap.id} ('{trap.name}'). Invalid move: '{move_san}'. Error: {e}")
                continue
        return index

    def _get_matches_for_current_position(self, game_state: GameState) -> List[Tuple[QueenTrap, int]]:
        """Găsește TOATE capcanele custom care trec prin poziția curentă."""
        if game_state.is_recording:
            return []
        current_fen = game_state.board.shredder_fen()
        matching_entries = self.position_index.get(current_fen, [])

        return [(self.id_to_trap_map[trap_id], move_index) 
                for trap_id, move_index in matching_entries if trap_id in self.id_to_trap_map]
    
    def force_reload(self):
        """Forțează reîncărcarea datelor din repository și reconstruirea indexului."""
        print("[QUEEN TRAP SERVICE] Forcing data reload...")
        self.all_traps = self.repository.get_all_traps()
        self.id_to_trap_map = {trap.id: trap for trap in self.all_traps}
        self.position_index = self._create_position_index()
        self._save_index_to_cache()
        print("[QUEEN TRAP SERVICE] Reload complete.")

    def get_aggregated_suggestions(self, game_state: GameState) -> List[MoveSuggestion]:
        if game_state.board.turn != game_state.current_player: return []
        move_groups = defaultdict(list)

        if not game_state.move_history:
            for trap in self.all_traps:
                if trap.color == game_state.current_player and trap.moves:
                    key = 'checkmate' if 'Checkmate' in trap.trap_type else 'queen_hunter'
                    move_groups[(trap.moves[0], key)].append(trap.moves)
        else:
            matches = self._get_matches_for_current_position(game_state)
            for trap, move_index in matches:
                is_our_turn_in_trap = (move_index + 1) % 2 == (0 if trap.color == chess.WHITE else 1)
                if trap.color == game_state.current_player and len(trap.moves) > move_index + 1 and is_our_turn_in_trap:
                    next_move = trap.moves[move_index + 1]
                    continuation = trap.moves[move_index + 1:]
                    key = 'checkmate' if 'Checkmate' in trap.trap_type else 'queen_hunter'
                    move_groups[(next_move, key)].append(continuation)

        return [
            MoveSuggestion(
                suggested_move=move,
                trap_count=len(lines),
                # CORECȚIE: lines[0] este deja continuarea completă
                example_trap_line=lines[0], 
                trap_type=type
            ) for (move, type), lines in move_groups.items()
        ]

    def get_most_common_response(self, game_state: GameState) -> Optional[str]:
        """Găsește cel mai comun răspuns al adversarului pentru capcanele de regină."""
        if game_state.board.turn == game_state.current_player:
            return None

        matches = self._get_matches_for_current_position(game_state)
        response_counts = defaultdict(int)
        
        for trap, move_index in matches:
            if len(trap.moves) > move_index + 1:
                opponent_response_san = trap.moves[move_index + 1]
                response_counts[opponent_response_san] += 1
        
        if not response_counts:
            return None
            
        return max(response_counts, key=response_counts.get)

    def add_new_trap_dynamically(self, trap: QueenTrap):
        """Adaugă o capcană nouă în memorie fără a reîncărca totul."""
        if trap.id is None: return

        self.all_traps.append(trap)
        self.id_to_trap_map[trap.id] = trap

        board = chess.Board()
        try:
            for i, move_san in enumerate(trap.moves):
                clean_san = move_san.replace('#', '').replace('+', '')
                move = board.parse_san(clean_san)
                board.push(move)
                positional_fen = board.shredder_fen()
                self.position_index[positional_fen].append((trap.id, i))
        except ValueError:
            print(f"[DYNAMIC INDEX] Failed to index new queen trap {trap.id}")
            return
            
        print(f"[QUEEN TRAP SERVICE] Trap {trap.id} added dynamically to memory.")

    def count_matching_traps(self, game_state: GameState) -> int:
        """Numără capcanele custom care se potrivesc cu poziția curentă."""
        if not self.all_traps or game_state.is_recording:
            return 0
            
        if not game_state.move_history:
             return sum(1 for trap in self.all_traps if trap.color == game_state.current_player)

        return len(self._get_matches_for_current_position(game_state))

class PGNImportService:
    """Service for importing traps from PGN files."""
    
    def __init__(self, repository: TrapRepository):
        self.repository = repository
    
    def import_from_file(self, file_path: str, max_moves: int = 25, checkmate_only: bool = False, progress_callback=None) -> Tuple[int, int, int]:
        """
        Parses a PGN file and calls the repository to bulk import and index the traps.
        Returns (total_inserted, white_inserted, black_inserted).
        """
        import logging # Add the import for clarity

        logging.info(f"[PGN IMPORT] Starting import and index process for: {file_path}")
        
        try:
            white_traps, black_traps = self._parse_pgn_file(file_path, max_moves, checkmate_only)
            all_traps_found = white_traps + black_traps
            
            if not all_traps_found:
                logging.warning(f"[PGN IMPORT] No valid traps found in {file_path}. Nothing to do.")
                return 0, 0, 0

            logging.info(f"[PGN IMPORT] Found {len(white_traps)} white and {len(black_traps)} black potential traps.")
            logging.info(f"Total: {len(all_traps_found)}. Passing to repository for import and indexing...")

            inserted_count, white_count, black_count = self.repository.bulk_import_and_index_traps(all_traps_found)
            
            logging.info(f"[PGN IMPORT] Process for file completed. Repository inserted {white_count} white, {black_count} black new traps.")
            
            return inserted_count, white_count, black_count
            
        except Exception as e:
            # Replaced print with logging.error
            logging.error(f"[PGN IMPORT ERROR] Main import process failed: {e}", exc_info=True)
            return 0, 0, 0

    def import_from_folder(self, folder_path: str, max_moves: int = 25, checkmate_only: bool = False) -> Tuple[int, int, int]:
        """
        Import traps from all PGN files in a folder sequentially.
        Returns (total_inserted, total_white_inserted, total_black_inserted).
        """
        import logging # Adăugăm importul aici pentru claritate

        total_white = 0
        total_black = 0
        
        pgn_files = sorted(list(Path(folder_path).glob("*.pgn")))
        if not pgn_files:
            logging.warning(f"[FOLDER IMPORT] Nu am găsit fișiere PGN în {folder_path}")
            return 0, 0, 0
        
        num_files = len(pgn_files)
        logging.info(f"Începe procesarea unui folder. S-au găsit {num_files} fișiere PGN.")
        start_time = time.time()
        
        for i, pgn_file in enumerate(pgn_files):
            # Am înlocuit print-ul cu logging.info pentru a avea timestamp
            logging.info(f"--- Procesare fișier {i + 1}/{num_files}: {pgn_file.name} ---")
            try:
                _, white_count, black_count = self.import_from_file(str(pgn_file), max_moves, checkmate_only)
                total_white += white_count
                total_black += black_count
            except Exception as e:
                # Am înlocuit print-ul cu logging.error
                logging.error(f"A apărut o eroare critică la procesarea {pgn_file.name}: {e}", exc_info=True)
                logging.warning("--- Se trece la următorul fișier. ---")
                continue

        elapsed = time.time() - start_time
        
        # Am înlocuit print-urile din sumar cu logging.info
        logging.info("--- SUMAR IMPORT FOLDER ---")
        logging.info(f"- Fișiere procesate: {num_files}")
        logging.info(f"- Total capcane noi pentru ALB adăugate: {total_white}")
        logging.info(f"- Total capcane noi pentru NEGRU adăugate: {total_black}")
        logging.info(f"- TOTAL CAPCANE UNICE NOI ADĂUGATE: {total_white + total_black}")
        logging.info(f"- Timp total: {elapsed:.2f} secunde")
        
        return total_white + total_black, total_white, total_black
    
    def _parse_pgn_file(self, file_path: str, max_moves: int, checkmate_only: bool) -> Tuple[List['ChessTrap'], List['ChessTrap']]:
        """
        Optimized parser that processes games in portions (chunks) using multiprocessing,
        reading the PGN file in a streaming fashion to handle very large files.
        
        Arguments:
            file_path (str): The path to the PGN file to import.
            max_moves (int): The maximum number of semi-moves for the traps to import.
            checkmate_only (bool): Whether to import only checkmating lines.
            
        Returns:
            Tuple[List[ChessTrap], List[ChessTrap]]: A pair of lists,
            the first containing white traps and the second black traps found.
        """
        print(f"[DEBUG PGN PARSE] Opening file with MULTICORE method (CONTROLLED STREAMING): {file_path}")
        
        # This inner function (generator) will read and return
        # the PGN game strings, WITHOUT storing all of them in memory at once.
        def game_string_generator():
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as pgn_file:
                current_game_lines = []
                for line in pgn_file:
                    line = line.strip()
                    if line.startswith('[') or line:  # Header line or moves
                        current_game_lines.append(line)
                    elif current_game_lines:  # Empty line = end of a PGN game
                        yield '\n'.join(current_game_lines) # Yield the complete game string
                        current_game_lines = [] # Reset for the next game
                if current_game_lines: # Don't forget the last game if file doesn't end with empty line
                    yield '\n'.join(current_game_lines)

        # This inner function (generator) groups elements from another generator into batches
        def batch_generator(source_generator, batch_size):
            current_batch = []
            for element in source_generator:
                current_batch.append(element)
                if len(current_batch) == batch_size:
                    yield current_batch # Yield the complete batch
                    current_batch = [] # Reset the batch
            if current_batch: # Yield the last batch, even if incomplete
                yield current_batch

        collected_white_traps = []
        collected_black_traps = []
        
        # --- THESE ARE THE LINES YOU WILL MODIFY FOR TESTING ---
        
        # Line 1: Number of workers (concurrent processes)
        # For an i5-13600K (20 logical threads), "8 workers" is a good starting choice for speed.
        # You can change this value based on your tests (e.g., 1, 2, 10, 14, 18, etc.)
        num_workers = 12 # <--- This line you will modify incrementally

        # Line 2: Size of each batch (number of PGN games in a chunk sent to a worker)
        # 250 games per batch is a good value for memory efficiency per chunk.
        # You can change this value based on your tests (e.g., 100, 500, 1000, etc.)
        streaming_batch_size = 10000 # <--- This line you will modify incrementally
        
        # --- NEW: Control the maximum number of chunks submitted at any time ---
        # This is CRUCIAL for limiting RAM usage.
        # It's typically (num_workers * a small multiplier like 1, 2, or 3)
        max_concurrent_chunks_in_queue = num_workers * 2 # Or 1, for stricter control, or 3 for more aggressive queuing
        
        # --- END OF LINES FOR MODIFICATION ---
        
        print(f"[DEBUG PGN PARSE] Using {num_workers} workers with a streaming batch size of {streaming_batch_size} games per batch.")
        print(f"[DEBUG PGN PARSE] Maximum concurrent chunks in queue: {max_concurrent_chunks_in_queue}")
        start_time = time.time()
        
        # Create the generator for PGN game batches
        # Convert to an iterator using iter() for consistent behavior across different Python versions
        game_batches_iterator = iter(batch_generator(game_string_generator(), streaming_batch_size))

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Prepare the worker function with fixed arguments using partial
            # IMPORTANT: The keyword arguments here (max_moves, checkmate_only) MUST match
            # the parameter names in the 'process_pgn_games_chunk' function definition.
            worker_processor = partial(process_pgn_games_chunk, 
                                       max_moves=max_moves, 
                                       checkmate_only=checkmate_only)
            
            futures = set() # Set to store active futures (tasks submitted to workers)
            
            # --- Initial submission: Fill the queue up to max_concurrent_chunks_in_queue ---
            # This ensures workers start processing immediately.
            for _ in range(max_concurrent_chunks_in_queue):
                try:
                    batch_to_submit = next(game_batches_iterator)
                    futures.add(executor.submit(worker_processor, batch_to_submit))
                except StopIteration:
                    # No more batches to submit from the generator, even at the start.
                    # This means the file might be very small, or all batches are submitted.
                    break 

            processed_chunks_count = 0
            
            # --- Main loop: Process results and submit new tasks ---
            # This loop continues as long as there are active tasks (futures).
            while futures:
                # Wait for at least one future to complete.
                # 'as_completed' yields futures one by one as they finish.
                # timeout=None means it will wait indefinitely until a future completes.
                for completed_future in as_completed(futures, timeout=None):
                    futures.remove(completed_future) # Remove the completed future from our set
                    
                    try:
                        # Get results from the completed future.
                        # The result of process_pgn_games_chunk is (white_traps, black_traps).
                        white_chunk, black_chunk = completed_future.result()
                        collected_white_traps.extend(white_chunk)
                        collected_black_traps.extend(black_chunk)
                        processed_chunks_count += 1
                        
                        # Print a progress message every 10 chunks processed.
                        if processed_chunks_count % 10 == 0:
                            print(f"  ... processed {processed_chunks_count} chunks ... Total traps found so far: White={len(collected_white_traps):,}, Black={len(collected_black_traps):,}")
                    except Exception as exc:
                        # Catch any exceptions that occurred during chunk processing in a worker.
                        print(f"  [ERROR] A chunk processing generated an exception: {exc}")
                        # Depending on requirements, you might want to re-raise a specific error,
                        # log more details about the faulty chunk, or just continue.

                    # --- Submit a new task if there are more batches AND room in the queue ---
                    # This is the "backpressure" mechanism. It ensures we maintain a steady
                    # pipeline of tasks without overloading the main process's memory.
                    # This inner while loop tries to add new tasks whenever a slot opens up
                    # until the queue is full again or the input generator is exhausted.
                    while len(futures) < max_concurrent_chunks_in_queue:
                        try:
                            next_batch_to_submit = next(game_batches_iterator)
                            futures.add(executor.submit(worker_processor, next_batch_to_submit))
                        except StopIteration:
                            # The game_batches_iterator is exhausted; no more batches to submit.
                            # Break out of this inner while loop. The outer while loop will
                            # then continue to drain any remaining active futures.
                            break 

        elapsed_time = time.time() - start_time
        print(f"[DEBUG PGN PARSE] All games processed in {elapsed_time:.2f} seconds")
        print(f"[DEBUG PGN PARSE] Found: {len(collected_white_traps):,} white traps, {len(collected_black_traps):,} black traps")
        
        return collected_white_traps, collected_black_traps


    def export_db_to_pgn_file(self, output_filepath: str):
        """
        Exports the entire traps database to a PGN file using a memory-efficient
        streaming approach.
        """
        print(f"[PGN EXPORT] Starting streaming export to {output_filepath}...")
        
        total_exported = 0
        try:
            # Deschidem fișierul de ieșire o singură dată
            with open(output_filepath, 'w', encoding='utf-8') as f:
                # Iterăm prin capcane folosind noul generator
                for i, trap in enumerate(self.repository.iterate_all_traps()):
                    # Construim header-ul PGN
                    headers = [
                        f'[Event "{trap.name or "Database Trap Export"}"]',
                        '[Site "Chess Trap Explorer DB"]',
                        f'[Date "{time.strftime("%Y.%m.%d")}"]',
                        f'[Round "{i + 1}"]',
                        f'[White "{"Player" if trap.color == chess.WHITE else "Opponent"}"]',
                        f'[Black "{"Player" if trap.color == chess.BLACK else "Opponent"}"]',
                        f'[Result "{"1-0" if trap.color == chess.WHITE else "0-1"}"]'
                    ]
                    
                    # Formatăm mutările
                    moves_text = ""
                    for move_idx, move_san in enumerate(trap.moves):
                        if move_idx % 2 == 0:
                            moves_text += f"{move_idx // 2 + 1}. {move_san} "
                        else:
                            moves_text += f"{move_san} "
                    
                    # Scriem direct în fișier
                    f.write("\n".join(headers) + "\n\n")
                    f.write(moves_text.strip() + "\n\n")
                    
                    total_exported += 1
                    if total_exported % 10000 == 0:
                        print(f"  ... exported {total_exported} traps ...")

        except Exception as e:
            print(f"[PGN EXPORT ERROR] An error occurred: {e}")
            return 0

        print(f"[PGN EXPORT] Complete. Successfully exported {total_exported} traps.")
        return total_exported



  
class DatabaseAuditor:
    """
    Handles the verification and cleaning of the traps database.
    """
    def __init__(self, repository: TrapRepository):
        self.repository = repository

    def run_audit(self, max_moves: int) -> Tuple[str, bool]:
        """
        Runs all audit checks and returns a summary report and a boolean
        indicating if any changes were made to the database.
        """
        print("[AUDIT] Starting database audit...")
        start_time = time.time()
        
        # Flag pentru a urmări dacă facem vreo modificare
        changes_made = False
        
        all_traps = self.repository.get_all_traps()
        if not all_traps:
            return "Audit Complete: The database is empty.", False

        # ... (logica de a găsi duplicate, color_updates, etc. rămâne identică) ...
        seen_signatures = set()
        duplicate_ids = []
        for trap in all_traps:
            signature = (json.dumps(trap.moves), trap.color)
            if signature in seen_signatures:
                duplicate_ids.append(trap.id)
            else:
                seen_signatures.add(signature)
        
        color_updates = []
        no_checkmate_ids = []
        too_long_ids = []
        
        for trap in all_traps:
            if trap.id in duplicate_ids:
                continue
            if not trap.moves or not trap.moves[-1].endswith('#'):
                no_checkmate_ids.append(trap.id)
                continue
            num_moves = len(trap.moves)
            expected_color = chess.WHITE if num_moves % 2 != 0 else chess.BLACK
            if trap.color != expected_color:
                color_updates.append((expected_color, trap.id))
            if num_moves > max_moves:
                too_long_ids.append(trap.id)

        # --- Perform Database Operations ---
        all_ids_to_delete = set(duplicate_ids) | set(no_checkmate_ids) | set(too_long_ids)
        
        if all_ids_to_delete:
            print(f"[AUDIT] Deleting {len(all_ids_to_delete)} invalid or duplicate traps.")
            self.repository.delete_traps_by_ids(list(all_ids_to_delete))
            changes_made = True  # AM FĂCUT MODIFICĂRI!

        if color_updates:
            print(f"[AUDIT] Correcting color for {len(color_updates)} traps.")
            self.repository.update_trap_colors(color_updates)
            changes_made = True  # AM FĂCUT MODIFICĂRI!
            
        elapsed = time.time() - start_time
        print(f"[AUDIT] Audit finished in {elapsed:.2f} seconds. Changes made: {changes_made}")

        # --- Generate Report ---
        report = (
            f"Audit Complete!\n\n"
            f"  - Duplicates removed: {len(duplicate_ids)}\n"
            f"  - Color mismatches fixed: {len(color_updates)}\n"
            f"  - Traps without '#' removed: {len(no_checkmate_ids)}\n"
            f"  - Traps longer than {max_moves} moves removed: {len(too_long_ids)}\n\n"
            f"Total entries removed: {len(all_ids_to_delete)}\n"
            f"Database was modified: {'Yes' if changes_made else 'No'}"
        )
        return report, changes_made

class OpeningDatabase:
    """Bază de date hibridă pentru deschideri, cu logging inteligent."""
    
    def __init__(self, db_path: str = "openings.db"):
        self.db_path = db_path
        self.conn = None
        # --- NOILE VARIABILE PENTRU LOGGING STATIC ---
        self.last_white_desc = ""
        self.last_black_desc = ""
        self.last_theory = ""
        # -------------------------------------------
        
        if os.path.exists(self.db_path):
            try:
                db_uri = f"file:{self.db_path}?mode=ro"
                self.conn = sqlite3.connect(db_uri, uri=True, check_same_thread=False)
                count = self.conn.cursor().execute("SELECT COUNT(*) FROM openings").fetchone()[0]
                print(f"[DEBUG INIT] Connection to opening book '{self.db_path}' successful. Found {count} entries.")
            except sqlite3.Error as e:
                print(f"[ERROR] Could not connect to opening book database: {e}")

    def _check_system_fingerprint(self, board: chess.Board, color: chess.Color) -> Optional[str]:
        systems_for_color = SYSTEM_FINGERPRINTS.get(color, {})
        for system_name, data in systems_for_color.items():
            all_pieces_in_place = all(
                (piece_on_square := board.piece_at(square)) and
                piece_on_square.piece_type == piece_type and
                piece_on_square.color == color
                for piece_type, squares in data["pieces"].items()
                for square in squares
            )
            if all_pieces_in_place:
                return system_name
        return None

    def _get_opening_name_from_db(self, moves: List[str]) -> Optional[OpeningInfo]:
        if not self.conn or not moves: return None
        try:
            cursor = self.conn.cursor()
            for length in range(len(moves), 0, -1):
                moves_json = json.dumps(moves[:length])
                cursor.execute("SELECT name, eco_code FROM openings WHERE moves_json = ?", (moves_json,))
                if result := cursor.fetchone():
                    return OpeningInfo(name=result[0], eco_code=result[1])
            return None
        except sqlite3.Error as e:
            print(f"[DB ERROR] Error querying opening book: {e}")
            return None

    def get_opening_phase_info(self, board: chess.Board, moves: List[str]) -> Tuple[str, str]:
        if not moves:
            # La începutul partidei, resetăm totul
            self.last_white_desc = "Starting Position"
            self.last_black_desc = "Starting Position"
            self.last_theory = None
            return self.last_white_desc, self.last_black_desc

        # Cine a făcut ultima mutare?
        last_move_color = not board.turn 

        # 1. Detectăm întotdeauna sistemele
        white_system = self._check_system_fingerprint(board, chess.WHITE)
        black_system = self._check_system_fingerprint(board, chess.BLACK)
        
        # 2. Găsim teoria
        theoretical_opening = self._get_opening_name_from_db(moves)
        theory_name = f"{theoretical_opening.name} ({theoretical_opening.eco_code})" if theoretical_opening else None
        
        # Pornim de la descrierile anterioare
        final_white = self.last_white_desc
        final_black = self.last_black_desc

        # Prioritatea 1: Dacă un sistem a fost detectat, el devine starea de bază pentru acel jucător
        if white_system:
            final_white = white_system
        if black_system:
            final_black = black_system

        # Prioritatea 2: Teoria. O atribuim jucătorului care a făcut mutarea ce a condus la ea.
        if theory_name and theory_name != self.last_theory:
            # A apărut o nouă teorie!
            is_black_theory = "defense" in theory_name.lower() or "defence" in theory_name.lower() or "counter" in theory_name.lower()
            is_white_theory = "attack" in theory_name.lower() or "gambit" in theory_name.lower() or "opening" in theory_name.lower()

            if last_move_color == chess.WHITE:
                # Albul a făcut mutarea care a schimbat teoria
                if not white_system or (white_system and white_system.lower() in theory_name.lower()):
                     final_white = theory_name
            
            elif last_move_color == chess.BLACK:
                # Negrul a făcut mutarea
                if not black_system or (black_system and black_system.lower() in theory_name.lower()):
                     final_black = theory_name

            # Cazul special pentru deschideri neutre, ca "Italian Game"
            if not is_white_theory and not is_black_theory:
                # Dacă teoria e neutră, o setăm pentru ambii dacă nu au sisteme
                if not white_system: final_white = theory_name
                if not black_system: final_black = theory_name

        # Fallback final pentru a nu rămâne cu "Starting Position"
        if final_white == "Starting Position": final_white = "Developing"
        if final_black == "Starting Position": final_black = "Developing"
        
        # Logging și actualizare stare (rămâne la fel)
        if final_white != self.last_white_desc or final_black != self.last_black_desc or theory_name != self.last_theory:
            print("\n--- Opening State Update ---")
            print(f"  Move by: {'White' if last_move_color == chess.WHITE else 'Black'}")
            print(f"  Detected White System: {white_system or 'N/A'}")
            print(f"  Detected Black System: {black_system or 'N/A'}")
            print(f"  Detected Theory Line: {theory_name or 'N/A'}")
            print(f"  ==> Displaying: [W: {final_white}] | [B: {final_black}]")
            
            self.last_white_desc = final_white
            self.last_black_desc = final_black
            self.last_theory = theory_name

        return final_white, final_black

    def get_total_openings(self) -> int:
        """Returns the total number of opening lines in the database."""
        if not self.conn:
            return 0
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM openings")
            count = cursor.fetchone()
            return count[0] if count else 0
        except sqlite3.Error as e:
            print(f"[DB ERROR] Could not count openings: {e}")
            return 0

class SettingsService:
    """Service for managing application settings."""
    
    def __init__(self, settings_file: str = "settings.json"):
        self.settings_file = settings_file
        self.default_settings = {
            "last_pgn_directory": "",
            "pgn_import_max_moves": 25
        }
    
    def load_settings(self) -> Dict:
        """Load settings from file."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    return {**self.default_settings, **json.load(f)}
        except Exception as e:
            print(f"[DEBUG] Error loading settings: {e}")
        
        return self.default_settings.copy()
    
    def save_settings(self, settings: Dict) -> None:
        """Save settings to file."""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"[DEBUG] Error saving settings: {e}")
    
    def update_setting(self, key: str, value) -> None:
        """Update a single setting."""
        settings = self.load_settings()
        settings[key] = value
        self.save_settings(settings)

# UI Components
class PieceImageLoader:
    """Loads and caches chess piece images."""
    
    def __init__(self, square_size: int = 64):
        self.square_size = square_size
        self.piece_images = {}
        self._load_piece_images()
    
    def _load_piece_images(self) -> None:
        """Load chess piece images."""
        piece_symbols = {
            chess.PAWN: 'p', chess.ROOK: 'r', chess.KNIGHT: 'n',
            chess.BISHOP: 'b', chess.QUEEN: 'q', chess.KING: 'k'
        }
        
        for piece_type, symbol in piece_symbols.items():
            for color in [chess.WHITE, chess.BLACK]:
                color_prefix = 'w' if color == chess.WHITE else 'b'
                filename = f"{color_prefix}{symbol}.png"
                
                try:
                    # Try to load from pieces folder
                    image_path = os.path.join("pieces", filename)
                    if os.path.exists(image_path):
                        image = pygame.image.load(image_path)
                        image = pygame.transform.scale(image, (self.square_size, self.square_size))
                        self.piece_images[(piece_type, color)] = image
                    else:
                        # Create placeholder if image not found
                        surface = pygame.Surface((self.square_size, self.square_size), pygame.SRCALPHA)
                        color_rgb = (255, 255, 255) if color == chess.WHITE else (0, 0, 0)
                        pygame.draw.circle(surface, color_rgb, 
                                         (self.square_size//2, self.square_size//2), 
                                         self.square_size//3)
                        self.piece_images[(piece_type, color)] = surface
                
                except pygame.error as e:
                    print(f"[DEBUG] Error loading piece {filename}: {e}")
                    # Create error placeholder
                    surface = pygame.Surface((self.square_size, self.square_size))
                    surface.fill((255, 0, 0))  # Red placeholder
                    self.piece_images[(piece_type, color)] = surface
    
    def get_piece_image(self, piece: chess.Piece) -> pygame.Surface:
        """Get the image for a chess piece."""
        return self.piece_images.get((piece.piece_type, piece.color))

class InputHandler:
    """Handles user input events."""
    
    def __init__(self, config: UIConfig):
        self.config = config
    
    def handle_button_click(self, pos: Tuple[int, int], button_rects: Dict[str, pygame.Rect]) -> Optional[str]:
        """Handle button clicks and return action name."""
        for action, rect in button_rects.items():
            if rect.collidepoint(pos):
                return action
        return None
    
    def get_square_from_mouse(self, pos: Tuple[int, int], flipped: bool = False) -> Optional[chess.Square]:
        """Convert mouse position to chess square."""
        x, y = pos[0] - self.config.LEFT_MARGIN, pos[1] - self.config.TOP_MARGIN
        
        if not (0 <= x < self.config.BOARD_SIZE and 0 <= y < self.config.BOARD_SIZE):
            return None
        
        col_screen, row_screen = x // self.config.SQUARE_SIZE, y // self.config.SQUARE_SIZE
        col_logic = 7 - col_screen if flipped else col_screen
        row_logic = row_screen if flipped else 7 - row_screen
        
        if not (0 <= col_logic < 8 and 0 <= row_logic < 8):
            return None
        
        square = chess.square(col_logic, row_logic)
        return square

class Renderer:
    """Handles all rendering operations."""
    
    def __init__(self, config: UIConfig, piece_loader: PieceImageLoader):
        self.config = config
        self.piece_loader = piece_loader
        
        pygame.font.init()
        # Mărim fonturile pentru a se potrivi cu noua rezoluție
        self.font = pygame.font.Font(None, 32)
        self.small_font = pygame.font.Font(None, 24)
        self.large_font = pygame.font.Font(None, 48)
    
    
    def render_game_screen(self, surface: pygame.Surface, state: GameState, 
                           suggestions: List[MoveSuggestion], total_matching_traps: int,
                           flipped: bool) -> Dict[str, pygame.Rect]:
        """Render the main game screen by orchestrating other render methods."""
        surface.fill((30, 30, 30))
        
        # Butoanele vor fi colectate din diversele panouri
        all_button_rects = {}
        
        # 1. Randează panoul de control
        # NOTĂ: Pentru a obține butoanele, ar trebui să pasăm și move_history, dar simplificăm aici
        # deoarece această metodă nu este folosită activ în bucla principală acum.
        control_rects = self.render_control_panel(surface, state, state.move_history)
        all_button_rects.update(control_rects)
        
        # 2. Randează tabla (care acum include și highlights)
        self.render_board(surface, state, flipped)
        
        # 3. Randează piesele
        self.render_pieces(
            surface, 
            state.board, 
            self.piece_loader, 
            state.selected_square, 
            flipped,
            state.dragging_piece,
            state.drag_pos
        )
        
        # 4. Randează panoul de sugestii
        # --- AICI ESTE CORECȚIA CRUCIALĂ ---
        # Adăugăm argumentul 'state' care lipsea.
        suggestions_button_rects = self.render_suggestions_panel(
            surface, 
            state, # <-- ACEST ARGUMENT LIPSEA
            suggestions, 
            total_matching_traps
        )
        all_button_rects.update(suggestions_button_rects)
        
        # 5. Randează statusul
        # NOTĂ: similar cu panoul de control, logica de a obține info e în afara acestei funcții
        # așa că vom folosi un placeholder dacă e apelată direct.
        white_info, black_info = "White", "Black" # Placeholder
        self.render_status(surface, state, white_info, black_info)
        
        return all_button_rects
    
    def render_control_panel(self, surface: pygame.Surface, state: GameState, move_history: List[str]) -> Dict[str, pygame.Rect]:
        """Render the main control panel with integrated functionality."""
        button_rects = {}
        
        panel_rect = pygame.Rect(0, 0, self.config.BUTTONS_WIDTH, self.config.HEIGHT)
        pygame.draw.rect(surface, self.config.PANEL_COLOR, panel_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, panel_rect, 2)
        
        y_offset = 10
        title_surface = self.font.render("Controls:", True, self.config.TEXT_COLOR)
        surface.blit(title_surface, (10, y_offset))
        y_offset += 40

        # Butoanele de navigație rămân la fel
        nav_buttons = [("<", "one_back"), (">", "one_forward"), ("|<", "to_start"), (">|", "to_end")]
        button_width, button_height, spacing = 80, 35, 10
        for i, (text, action) in enumerate(nav_buttons):
            col, row = i % 2, i // 2
            rect = pygame.Rect(20 + col * (button_width + spacing), y_offset + row * (button_height + spacing), button_width, button_height)
            pygame.draw.rect(surface, self.config.BUTTON_COLOR, rect, border_radius=3)
            pygame.draw.rect(surface, self.config.BORDER_COLOR, rect, 1, border_radius=3)
            text_surf = self.small_font.render(text, True, self.config.TEXT_COLOR)
            surface.blit(text_surf, text_surf.get_rect(center=rect.center))
            button_rects[action] = rect
        y_offset += 2 * (button_height + spacing) + 10

        # Butonul contextual pentru schimbarea culorii
        if state.current_player == chess.WHITE:
            text, action = "Play as Black", "play_as_black"
        else:
            text, action = "Play as White", "play_as_white"
        
        rect = pygame.Rect(20, y_offset, self.config.BUTTONS_WIDTH - 40, 35)
        pygame.draw.rect(surface, (100, 100, 100), rect, border_radius=3)
        text_surf = self.small_font.render(text, True, self.config.TEXT_COLOR)
        surface.blit(text_surf, text_surf.get_rect(center=rect.center))
        button_rects[action] = rect
        y_offset += 45

        # Butoane de acțiune principale (FĂRĂ "Reset Game")
        action_buttons = [
            ("Record New Trap", "record", (0, 120, 0)),
            ("Import / Audit", "import_pgn", (0, 100, 150)),
            ("Database Info", "db_info", (0, 80, 120)),
        ]
        for text, action, color in action_buttons:
            rect = pygame.Rect(20, y_offset, self.config.BUTTONS_WIDTH - 40, 35)
            # Logica pentru schimbarea textului butonului "record" rămâne
            if action == "record" and state.is_recording:
                color, text = (180, 0, 0), "Confirm/Stop"
            pygame.draw.rect(surface, color, rect, border_radius=3)
            text_surf = self.small_font.render(text, True, self.config.TEXT_COLOR)
            surface.blit(text_surf, text_surf.get_rect(center=rect.center))
            button_rects[action] = rect
            y_offset += 45

        # Panoul de Istoric (rămâne neschimbat)
        history_y_start = y_offset + 20
        history_panel_rect = pygame.Rect(10, history_y_start, self.config.BUTTONS_WIDTH - 20, self.config.HEIGHT - history_y_start - 20)
        pygame.draw.rect(surface, (40, 40, 40), history_panel_rect, border_radius=5)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, history_panel_rect, 1, border_radius=5)

        history_title_surf = self.small_font.render("Move History:", True, (200, 200, 200))
        surface.blit(history_title_surf, (history_panel_rect.x + 10, history_panel_rect.y + 10))

        history_text = ""
        for i, move in enumerate(move_history):
            if i % 2 == 0:
                history_text += f"{i//2 + 1}. {move} "
            else:
                history_text += f"{move} "
        
        def draw_text_wrapped(surf, text, font, color, rect):
            words = text.split(' ')
            lines = []
            current_line = ""
            for word in words:
                if font.size(current_line + word)[0] < rect.width - 20:
                    current_line += word + " "
                else:
                    lines.append(current_line)
                    current_line = word + " "
            lines.append(current_line)
            
            y_text_offset = rect.y + 35
            for line in lines:
                if y_text_offset + font.get_height() > rect.y + rect.height - 45:
                    break
                line_surf = font.render(line, True, color)
                surf.blit(line_surf, (rect.x + 10, y_text_offset))
                y_text_offset += font.get_height()
                
        draw_text_wrapped(surface, history_text.strip(), self.small_font, self.config.TEXT_COLOR, history_panel_rect)
        
        copy_button_rect = pygame.Rect(history_panel_rect.centerx - 50, history_panel_rect.bottom - 35, 100, 25)
        pygame.draw.rect(surface, (80, 80, 150), copy_button_rect, border_radius=5)
        copy_text_surf = self.small_font.render("Copy PGN", True, self.config.TEXT_COLOR)
        surface.blit(copy_text_surf, copy_text_surf.get_rect(center=copy_button_rect.center))
        button_rects["copy_pgn"] = copy_button_rect
        
        return button_rects
        
    def render_board(self, surface: pygame.Surface, state: GameState, flipped: bool = False) -> None:
        """Render the chess board and highlights."""
        # Desenarea pătrățelelor
        for row in range(8):
            for col in range(8):
                x = self.config.LEFT_MARGIN + col * self.config.SQUARE_SIZE
                y = self.config.TOP_MARGIN + row * self.config.SQUARE_SIZE
                color = self.config.LIGHT_SQUARE if (row + col) % 2 == 0 else self.config.DARK_SQUARE
                pygame.draw.rect(surface, color, pygame.Rect(x, y, self.config.SQUARE_SIZE, self.config.SQUARE_SIZE))
        
        # Desenarea highlight-ului
        if state.highlighted_squares and state.highlight_color:
            from_sq, to_sq = state.highlighted_squares
            for sq in [from_sq, to_sq]:
                col_logic = chess.square_file(sq)
                row_logic = chess.square_rank(sq)
                
                # --- AICI ESTE CORECȚIA ESENȚIALĂ ---
                # Coordonata X (coloana) depinde de 'flipped'
                col_screen = 7 - col_logic if flipped else col_logic
                # Coordonata Y (rândul) este MEREU inversată față de logică,
                # DAR depinde și de 'flipped'
                row_screen = row_logic if flipped else 7 - row_logic
                
                x = self.config.LEFT_MARGIN + col_screen * self.config.SQUARE_SIZE
                y = self.config.TOP_MARGIN + row_screen * self.config.SQUARE_SIZE
                
                highlight_surface = pygame.Surface((self.config.SQUARE_SIZE, self.config.SQUARE_SIZE), pygame.SRCALPHA)
                highlight_surface.fill(state.highlight_color)
                surface.blit(highlight_surface, (x, y))

        # Desenarea conturului și a coordonatelor
        board_rect = pygame.Rect(self.config.LEFT_MARGIN, self.config.TOP_MARGIN, self.config.BOARD_SIZE, self.config.BOARD_SIZE)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, board_rect, 3)
        for i in range(8):
            file_letter = chr(ord('a') + (7 - i if flipped else i))
            file_surface = self.small_font.render(file_letter, True, self.config.TEXT_COLOR)
            file_x = self.config.LEFT_MARGIN + i * self.config.SQUARE_SIZE + self.config.SQUARE_SIZE // 2 - file_surface.get_width() // 2
            file_y = self.config.TOP_MARGIN + self.config.BOARD_SIZE + 10
            surface.blit(file_surface, (file_x, file_y))
            
            rank_number = str(i + 1 if flipped else 8 - i)
            rank_surface = self.small_font.render(rank_number, True, self.config.TEXT_COLOR)
            rank_x = self.config.LEFT_MARGIN - 20 - rank_surface.get_width()
            rank_y = self.config.TOP_MARGIN + i * self.config.SQUARE_SIZE + self.config.SQUARE_SIZE // 2 - rank_surface.get_height() // 2
            surface.blit(rank_surface, (rank_x, rank_y))

        
    def render_pieces(self, surface: pygame.Surface, board: chess.Board, 
                     piece_loader: PieceImageLoader, selected_square: Optional[chess.Square] = None,
                     flipped: bool = False, dragging_piece: Optional[chess.Piece] = None,
                     drag_pos: Optional[Tuple[int, int]] = None) -> None:
        """Render chess pieces on the board."""
        for r_logic in range(8):
            for c_logic in range(8):
                # --- CORECȚIE APLICATĂ ȘI AICI PENTRU CONSISTENȚĂ ---
                col_screen = 7 - c_logic if flipped else c_logic
                row_screen = r_logic if flipped else 7 - r_logic
                
                square = chess.square(c_logic, r_logic)
                piece = board.piece_at(square)
                
                if piece and square == selected_square and dragging_piece:
                    continue
                
                if piece:
                    piece_image = piece_loader.get_piece_image(piece)
                    if piece_image:
                        x = self.config.LEFT_MARGIN + col_screen * self.config.SQUARE_SIZE
                        y = self.config.TOP_MARGIN + row_screen * self.config.SQUARE_SIZE
                        
                        if square == selected_square and not dragging_piece:
                            highlight_surface = pygame.Surface((self.config.SQUARE_SIZE, self.config.SQUARE_SIZE), pygame.SRCALPHA)
                            highlight_surface.fill((255, 255, 0, 100))
                            surface.blit(highlight_surface, (x, y))
                        
                        surface.blit(piece_image, (x, y))
        
        if dragging_piece and drag_pos:
            piece_image = piece_loader.get_piece_image(dragging_piece)
            if piece_image:
                drag_x = drag_pos[0] - self.config.SQUARE_SIZE // 2
                drag_y = drag_pos[1] - self.config.SQUARE_SIZE // 2
                surface.blit(piece_image, (drag_x, drag_y))
    
    def render_suggestions_panel(self, surface: pygame.Surface, state: GameState, 
                                   suggestions: List[MoveSuggestion], 
                                   total_matching_traps: int) -> Dict[str, pygame.Rect]:
        """Render the suggestions panel, showing a success message if a trap is completed."""
        button_rects = {}
        panel_rect = pygame.Rect(self.config.WIDTH - self.config.SUGGESTIONS_WIDTH, 0, self.config.SUGGESTIONS_WIDTH, self.config.HEIGHT)
        pygame.draw.rect(surface, self.config.PANEL_COLOR, panel_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, panel_rect, 2)
        
        y_offset = 20
        
        # NOU: Verificăm dacă există un mesaj de succes de afișat
        if state.trap_success_message:
            title_surface = self.font.render("Trap Status:", True, self.config.TEXT_COLOR)
            surface.blit(title_surface, (panel_rect.x + 10, y_offset))
            y_offset += 80
            
            # Desenăm mesajul de succes pe mai multe linii
            lines = state.trap_success_message.split('\n')
            success_font = pygame.font.Font(None, 36)
            line_height = success_font.get_height() + 5

            for i, line in enumerate(lines):
                success_surface = success_font.render(line, True, (100, 255, 100)) # Verde deschis
                text_rect = success_surface.get_rect(centerx=panel_rect.centerx, y=y_offset + i * line_height)
                surface.blit(success_surface, text_rect)
            return button_rects # Ne oprim aici, nu mai afișăm sugestii

        # --- Logica veche de afișare a sugestiilor ---
        title_surface = self.font.render("Available Moves:", True, self.config.TEXT_COLOR)
        surface.blit(title_surface, (panel_rect.x + 10, y_offset))
        y_offset += 40
        
        traps_formatted = f"{total_matching_traps:_}".replace("_", " ")
        count_text = f"Matching traps found: {traps_formatted}"
        count_surface = self.small_font.render(count_text, True, (255, 255, 0))
        surface.blit(count_surface, (panel_rect.x + 10, y_offset))
        y_offset += 30
        
        suggestions_area = pygame.Rect(panel_rect.x + 10, y_offset, panel_rect.width - 20, panel_rect.height - y_offset - 20)
        pygame.draw.rect(surface, (40, 40, 40), suggestions_area)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, suggestions_area, 1)
        
        if suggestions:
            suggestion_height = 40
            for i, suggestion in enumerate(suggestions):
                if i * suggestion_height > suggestions_area.height - suggestion_height: break
                suggestion_y = suggestions_area.y + i * suggestion_height
                suggestion_rect_rel = pygame.Rect(5, 5, suggestions_area.width - 10, suggestion_height - 10)
                suggestion_rect_abs = suggestion_rect_rel.move(suggestions_area.x, suggestion_y)
                bg_color = self.config.SUGGESTION_PURPLE if suggestion.trap_type == 'queen_hunter' else self.config.SUGGESTION_BLUE
                prefix = "[Queen Hunter] " if suggestion.trap_type == 'queen_hunter' else ""
                pygame.draw.rect(surface, bg_color, suggestion_rect_abs)
                pygame.draw.rect(surface, self.config.BORDER_COLOR, suggestion_rect_abs, 1)
                trap_count_formatted = f"{suggestion.trap_count:_}".replace("_", " ")
                suggestion_text = f"{prefix}{suggestion.suggested_move} (in {trap_count_formatted} trap lines)"
                text_surface = self.small_font.render(suggestion_text, True, self.config.TEXT_COLOR)
                surface.blit(text_surface, (suggestion_rect_abs.x + 10, suggestion_rect_abs.y + 10))
                button_rects[f"suggestion_{i}"] = suggestion_rect_abs
        else:
            no_suggestions = self.small_font.render("No available traps for this line", True, (150, 150, 150))
            text_rect = no_suggestions.get_rect(center=suggestions_area.center)
            surface.blit(no_suggestions, text_rect)
                
        return button_rects
    
    def render_status(self, surface: pygame.Surface, state: GameState, white_info: str, black_info: str) -> None:
        """Render game status information including opening name from both perspectives."""
        
        # Stabilește culoarea textului pentru fiecare parte
        white_text_color = (255, 255, 255)
        black_text_color = (220, 220, 220)
        
        # Perspectiva JOS (de obicei albul)
        bottom_y = self.config.TOP_MARGIN + self.config.BOARD_SIZE + 45
        bottom_perspective_text = f"♔ {white_info}"
        bottom_surface = self.font.render(bottom_perspective_text, True, white_text_color)
        bottom_rect = bottom_surface.get_rect(center=(self.config.LEFT_MARGIN + self.config.BOARD_SIZE // 2, bottom_y))
        
        # Fundal pentru contrast jos
        bg_rect_bottom = bottom_rect.inflate(20, 10)
        
        # Perspectiva SUS (de obicei negrul)
        top_y = self.config.TOP_MARGIN - 30
        top_perspective_text = f"♛ {black_info}"
        top_surface = self.font.render(top_perspective_text, True, black_text_color)
        top_rect = top_surface.get_rect(center=(self.config.LEFT_MARGIN + self.config.BOARD_SIZE // 2, top_y))
        
        # Fundal pentru contrast sus
        bg_rect_top = top_rect.inflate(20, 10)
        
        # Desenează fundalurile
        pygame.draw.rect(surface, (40, 40, 40), bg_rect_bottom, border_radius=5)
        pygame.draw.rect(surface, (40, 40, 40), bg_rect_top, border_radius=5)
        
        # Desenează textul
        surface.blit(bottom_surface, bottom_rect)
        surface.blit(top_surface, top_rect)

        # Evidențiază chenarul jucătorului al cărui rând este
        highlight_color = (255, 255, 0)
        if state.board.turn == chess.WHITE:
            pygame.draw.rect(surface, highlight_color, bg_rect_bottom, 2, border_radius=5)
        else:
            pygame.draw.rect(surface, highlight_color, bg_rect_top, 2, border_radius=5)
        
        # Textul RECORDING (dacă este cazul)
        if state.is_recording:
            record_text = "RECORDING - Type trap name and press Enter"
            record_surface = self.small_font.render(record_text, True, (255, 100, 100))
            record_rect = record_surface.get_rect(centerx=self.config.LEFT_MARGIN + self.config.BOARD_SIZE // 2, y=5)
            surface.blit(record_surface, record_rect)

    
if QT_AVAILABLE:
    class QtInfoDialog(QDialog):
        """A dialog to display database statistics and provide management actions."""
        def __init__(self, stats: Dict[str, str], on_export_pgn, on_delete_custom_mates, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Database Statistics & Management")
            self.setMinimumWidth(400) # Mărim puțin lățimea
            
            self.on_export_pgn = on_export_pgn
            self.on_delete_custom_mates = on_delete_custom_mates

            main_layout = QVBoxLayout(self)
            
            # Partea de statistici (neschimbată)
            group_box = QGroupBox("Current Content")
            group_layout = QVBoxLayout()
            for key, value in stats.items():
                if key.startswith("separator"):
                    line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken)
                    group_layout.addWidget(line)
                else:
                    h_layout = QHBoxLayout()
                    key_label = QLabel(f"{key}:")
                    if key.strip().startswith('-'): key_label.setStyleSheet("padding-left: 20px;")
                    value_label = QLabel(value); value_label.setTextFormat(Qt.TextFormat.RichText); value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    h_layout.addWidget(key_label); h_layout.addWidget(value_label)
                    group_layout.addLayout(h_layout)
            group_box.setLayout(group_layout)
            main_layout.addWidget(group_box)
            
            # --- NOU: Secțiunea de acțiuni pentru custom checkmates ---
            actions_group_box = QGroupBox("Custom Checkmate Migration")
            actions_layout = QHBoxLayout()
            
            export_button = QPushButton("Export to PGN")
            export_button.setToolTip("Exports all manually recorded checkmates to a PGN file.")
            export_button.setStyleSheet("background-color: #A9DFBF;") # Verde
            export_button.clicked.connect(self.on_export_pgn)

            delete_button = QPushButton("Delete Custom Checkmates")
            delete_button.setToolTip("Deletes all manually recorded checkmates from the custom database.\nUse this after exporting and successfully importing them.")
            delete_button.setStyleSheet("background-color: #F5B7B1;") # Roșu
            delete_button.clicked.connect(self.on_delete_custom_mates)

            actions_layout.addWidget(export_button)
            actions_layout.addWidget(delete_button)
            actions_group_box.setLayout(actions_layout)
            main_layout.addWidget(actions_group_box)

            # Butonul de închidere
            ok_button = QPushButton("Close")
            ok_button.clicked.connect(self.accept)
            main_layout.addWidget(ok_button, 0, Qt.AlignmentFlag.AlignCenter)

    class QtSaveConfirmDialog(QDialog):
        """A dialog to confirm, cancel, or continue a trap recording."""
        SAVE, CANCEL, CONTINUE = 1, 2, 3

        def __init__(self, detected_trap_type: str, moves_san: List[str], parent=None):
            super().__init__(parent)
            self.setWindowTitle("Confirm Trap Recording")
            self.setMinimumWidth(400)
            self.result = self.CONTINUE

            layout = QVBoxLayout(self)
            info_label = QLabel(f"<b>Detected Potential Trap:</b><br>{detected_trap_type}")
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)
            
            group_box = QGroupBox("Recorded Moves")
            group_layout = QVBoxLayout()
            moves_text = ""
            for i, move in enumerate(moves_san):
                moves_text += f"{i//2 + 1}. {move} " if i % 2 == 0 else f"{move} "
            moves_label = QLabel(moves_text.strip())
            moves_label.setWordWrap(True)
            group_layout.addWidget(moves_label)
            group_box.setLayout(group_layout)
            layout.addWidget(group_box)
            
            button_layout = QHBoxLayout()
            save_button = QPushButton("✅ Save Trap")
            save_button.setStyleSheet("background-color: #B9F6CA;")
            save_button.clicked.connect(self.on_save)
            cancel_button = QPushButton("❌ Cancel Recording")
            cancel_button.setStyleSheet("background-color: #FF8A80;")
            cancel_button.clicked.connect(self.on_cancel)
            continue_button = QPushButton("➡️ Continue Recording")
            continue_button.clicked.connect(self.on_continue)
            button_layout.addWidget(cancel_button)
            button_layout.addWidget(continue_button)
            button_layout.addStretch()
            button_layout.addWidget(save_button)
            layout.addLayout(button_layout)

        def on_save(self): self.result = self.SAVE; self.accept()
        def on_cancel(self): self.result = self.CANCEL; self.accept()
        def on_continue(self): self.result = self.CONTINUE; self.accept()

        @staticmethod
        def get_decision(detected_trap_type: str, moves_san: List[str]):
            dialog = QtSaveConfirmDialog(detected_trap_type, moves_san)
            dialog.exec()
            return dialog.result

    class QtQueenTrapManager(QDialog):
        """A Qt Dialog to view, load, and delete recorded custom traps."""
        def __init__(self, queen_trap_repo: QueenTrapRepository, 
                     on_trap_deleted, on_trap_load, parent=None): # Am adăugat on_trap_load
            super().__init__(parent)
            self.repo = queen_trap_repo
            self.on_trap_deleted = on_trap_deleted
            self.on_trap_load = on_trap_load # Stocăm noul callback

            self.setWindowTitle("Manage Custom Traps")
            self.setMinimumSize(600, 500)
            
            self.main_layout = QVBoxLayout(self)
            
            # Scroll Area
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            
            self.container_widget = QWidget()
            self.list_layout = QVBoxLayout(self.container_widget)
            self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            
            scroll_area.setWidget(self.container_widget)
            self.main_layout.addWidget(scroll_area)
            
            # Buton de închidere
            close_button = QPushButton("Close")
            close_button.clicked.connect(self.accept)
            self.main_layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignCenter)

            self.populate_list()

        def populate_list(self):
            """Clears and repopulates the list of traps."""
            # Șterge widget-urile vechi pentru a evita duplicatele
            while self.list_layout.count():
                child = self.list_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            all_traps = self.repo.get_all_traps()
            # Sortăm după ID, de la cel mai nou la cel mai vechi. Este mai sigur decât a sorta după un string de dată.
            all_traps.sort(key=lambda t: t.id or 0, reverse=True) 
            
            if not all_traps:
                self.list_layout.addWidget(QLabel("No custom traps recorded yet."))
                return

            for trap in all_traps:
                frame = QFrame()
                frame.setFrameShape(QFrame.Shape.StyledPanel)
                layout = QHBoxLayout(frame)
                
                # --- AICI ESTE LOGICA ROBUSTĂ DE AFIȘARE A DATEI ---
                date_str = ""
                if trap.created_at:
                    # Afișăm data ca string, dar eliminăm milisecundele dacă există.
                    # Această metodă este foarte sigură și nu va genera erori.
                    clean_date_str = str(trap.created_at).split('.')[0]
                    date_str = f"<i>Recorded: {clean_date_str}</i><br>"

                label_text = (f"<b>{trap.name}</b> (Type: {trap.trap_type})<br>"
                              f"{date_str}"
                              f"<small>{' '.join(trap.moves)}</small>")
                
                label = QLabel(label_text)
                label.setWordWrap(True)
                
                load_button = QPushButton("Load")
                load_button.setFixedSize(80, 30)
                load_button.setToolTip("Load this trap onto the main board to view or edit it.")
                load_button.setStyleSheet("background-color: #A9DFBF;")
                load_button.clicked.connect(partial(self.load_trap, trap.moves))

                delete_button = QPushButton("Delete")
                delete_button.setFixedSize(80, 30)
                delete_button.setToolTip("Permanently delete this trap.")
                delete_button.setStyleSheet("background-color: #F5B7B1;")
                delete_button.clicked.connect(partial(self.delete_trap, trap.id))

                layout.addWidget(label)
                layout.addStretch()
                layout.addWidget(load_button)
                layout.addWidget(delete_button)
                self.list_layout.addWidget(frame)

        def load_trap(self, moves_san: List[str]):
            """Tells the main controller to load the moves and closes the dialog."""
            self.on_trap_load(moves_san)
            self.accept() # Închide dialogul după încărcare

        def delete_trap(self, trap_id: int):
            """Deletes a single trap after confirmation."""
            trap_to_delete = next((t for t in self.repo.get_all_traps() if t.id == trap_id), None)
            if not trap_to_delete:
                QMessageBox.warning(self, "Error", "Trap not found.")
                self.populate_list()
                return

            confirm_text = f"Are you sure you want to delete this trap?\n\n<b>{trap_to_delete.name}</b>"
            reply = QMessageBox.question(self, "Confirm Deletion", confirm_text,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                self.repo.delete_trap_by_id(trap_id)
                self.on_trap_deleted()
                self.populate_list()

    class QtImportWindow(QDialog):
        """A non-blocking Qt Dialog for PGN import settings."""
        def __init__(self, settings_service, on_start_file_import, on_start_folder_import, on_clear_db, on_start_audit, on_manage_queen_traps, on_export_db, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Import & Database Management")
            self.settings_service = settings_service
            # Stocăm callback-urile separate
            self.on_start_file_import = on_start_file_import
            self.on_start_folder_import = on_start_folder_import
            self.on_clear_db = on_clear_db
            self.on_start_audit = on_start_audit
            self.on_manage_queen_traps = on_manage_queen_traps
            self.on_export_db = on_export_db
            
            # Căi pentru sursele de import
            self.full_filepath = ""
            self.full_folderpath = ""

            self.settings = self.settings_service.load_settings()
            self.main_layout = QVBoxLayout(self)
            self._create_source_group()
            self._create_filters_group()
            self._create_database_group()
            self._create_actions_group()

        def start_audit(self):
            try: max_moves = int(self.max_moves_edit.text())
            except ValueError: max_moves = 25
            self.on_start_audit(max_moves)
            self.accept()

        def _create_source_group(self):
            group_box = QGroupBox("Import Source")
            layout = QVBoxLayout() # Trecem la layout vertical pentru a avea două rânduri
            
            # Rândul 1: Selectare Fișier
            file_layout = QHBoxLayout()
            select_file_button = QPushButton("Select PGN File...")
            select_file_button.clicked.connect(self.select_file)
            self.file_label = QLabel("No file selected.")
            file_layout.addWidget(select_file_button)
            file_layout.addWidget(self.file_label, 1)
            
            # Rândul 2: Selectare Folder
            folder_layout = QHBoxLayout()
            select_folder_button = QPushButton("Select Folder...")
            select_folder_button.clicked.connect(self.select_folder)
            self.folder_label = QLabel("No folder selected.")
            folder_layout.addWidget(select_folder_button)
            folder_layout.addWidget(self.folder_label, 1)

            layout.addLayout(file_layout)
            layout.addLayout(folder_layout)
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)

        def _create_filters_group(self):
            group_box = QGroupBox("Import Filters")
            layout = QVBoxLayout()
            h_layout = QHBoxLayout()
            h_layout.addWidget(QLabel("Max. semi-moves:"))
            self.max_moves_edit = QLineEdit(str(self.settings.get("pgn_import_max_moves", 25)))
            self.max_moves_edit.setFixedWidth(50)
            h_layout.addWidget(self.max_moves_edit)
            h_layout.addStretch()
            layout.addLayout(h_layout)
            self.checkmate_only_checkbox = QCheckBox("Import only checkmating lines")
            self.checkmate_only_checkbox.setChecked(self.settings.get("checkmate_only", False))
            layout.addWidget(self.checkmate_only_checkbox)
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)

        def _create_database_group(self):
            group_box = QGroupBox("Database")
            main_db_layout = QVBoxLayout()
            
            row1_layout = QHBoxLayout()
            audit_button = QPushButton("Audit DB")
            audit_button.setStyleSheet("background-color: #C1A7E2; font-weight: bold;")
            audit_button.clicked.connect(self.start_audit)
            manage_button = QPushButton("Manage Custom Traps")
            manage_button.setStyleSheet("background-color: #82E0AA;")
            manage_button.clicked.connect(self.on_manage_queen_traps)
            row1_layout.addWidget(audit_button)
            row1_layout.addWidget(manage_button)
            main_db_layout.addLayout(row1_layout)
            
            row2_layout = QHBoxLayout()
            export_button = QPushButton("Export DB to PGN")
            export_button.setStyleSheet("background-color: #A9DFBF; font-weight: bold;")
            export_button.setToolTip("Exports the entire checkmate traps database to a single PGN file.")
            export_button.clicked.connect(self.on_export_db)
            
            clear_button = QPushButton("Clear All Traps")
            clear_button.setStyleSheet("background-color: #FF8A80;")
            clear_button.clicked.connect(self.on_clear_db)

            row2_layout.addWidget(export_button)
            row2_layout.addStretch()
            row2_layout.addWidget(clear_button)
            main_db_layout.addLayout(row2_layout)
            
            group_box.setLayout(main_db_layout)
            self.main_layout.addWidget(group_box)
            
        def _create_actions_group(self):
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            self.main_layout.addWidget(line)
            
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(self.reject)
            self.start_button = QPushButton("START IMPORT")
            self.start_button.setStyleSheet("background-color: #B9F6CA; font-weight: bold;")
            self.start_button.clicked.connect(self.start_import)
            button_layout.addWidget(cancel_button)
            button_layout.addWidget(self.start_button)
            self.main_layout.addLayout(button_layout)

        def select_file(self):
            last_dir = self.settings.get("last_pgn_directory", "")
            filepath, _ = QFileDialog.getOpenFileName(self, "Select PGN File", last_dir, "PGN Files (*.pgn)")
            if filepath:
                self.full_filepath = filepath
                self.full_folderpath = "" # Resetează selecția de folder
                self.file_label.setText("..." + filepath[-35:])
                self.file_label.setStyleSheet("color: blue; font-weight: bold;")
                self.folder_label.setText("No folder selected.")
                self.folder_label.setStyleSheet("") # Stil normal
                self.settings_service.update_setting("last_pgn_directory", os.path.dirname(filepath))

        def select_folder(self):
            last_dir = self.settings.get("last_pgn_directory", "")
            folderpath = QFileDialog.getExistingDirectory(self, "Select Folder with PGN Files", last_dir)
            if folderpath:
                self.full_folderpath = folderpath
                self.full_filepath = "" # Resetează selecția de fișier
                self.folder_label.setText("..." + folderpath[-35:])
                self.folder_label.setStyleSheet("color: blue; font-weight: bold;")
                self.file_label.setText("No file selected.")
                self.file_label.setStyleSheet("") # Stil normal
                self.settings_service.update_setting("last_pgn_directory", folderpath)

        def start_import(self):
            if not self.full_filepath and not self.full_folderpath:
                QMessageBox.warning(self, "Warning", "Please select a PGN file or a folder first.")
                return
            
            try:
                max_moves = int(self.max_moves_edit.text())
            except ValueError:
                max_moves = 25
            checkmate_only = self.checkmate_only_checkbox.isChecked()

            # Salvează setările curente
            self.settings_service.update_setting("pgn_import_max_moves", max_moves)
            self.settings_service.update_setting("checkmate_only", checkmate_only)

            # Decide ce funcție de import să apeleze
            if self.full_filepath:
                self.on_start_file_import(self.full_filepath, max_moves, checkmate_only)
            elif self.full_folderpath:
                self.on_start_folder_import(self.full_folderpath, max_moves, checkmate_only)
            
            self.accept()

# Main Game Controller
class GameController:
    """Main controller that orchestrates the game."""
    
    def __init__(self):
        print("[DEBUG INIT] Initializing GameController...")
        
        self.qt_app = QApplication.instance() 
        if self.qt_app is None:
            self.qt_app = QApplication([])
        
        pygame.init()
        
        self.config = UIConfig()
        
        # Crearea repository-ului va declanșa acum automat migrarea bazei de date, dacă este necesar.
        self.trap_repository = TrapRepository()
        self.queen_trap_repository = QueenTrapRepository()
        
        # Serviciile vor fi create DUPĂ ce repository-ul a asigurat structura corectă a DB.
        self.trap_service = TrapService(self.trap_repository)
        self.queen_trap_service = QueenTrapService(self.queen_trap_repository)
        
        self.pgn_service = PGNImportService(self.trap_repository)
        self.settings_service = SettingsService()
        self.opening_db = OpeningDatabase()
        
        self.screen = pygame.display.set_mode((self.config.WIDTH, self.config.HEIGHT))
        pygame.display.set_caption("Chess Trap Trainer - Clean Architecture")
        
        self.piece_loader = PieceImageLoader(self.config.SQUARE_SIZE)
        self.input_handler = InputHandler(self.config)
        self.renderer = Renderer(self.config, self.piece_loader)
        
        self.current_state = GameState(board=chess.Board(), current_player=chess.WHITE)
        self.flipped = False
        self.move_history_forward = []
        self.current_suggestions = []
        
        self.total_matching_traps = 0
        
        print("[DEBUG INIT] GameController initialization complete! Will start game directly.")
    
    def run(self) -> None:
        print("[DEBUG MAIN] Starting main game loop...")
        clock = pygame.time.Clock()
        running = True
        
        # Pornim primul joc implicit ca Alb
        self._start_game(chess.WHITE)

        while running:
            if self.qt_app:
                self.qt_app.processEvents()
            
            events = pygame.event.get()
            
            if self.current_state.is_recording:
                # `text_input_visual` nu mai este folosit, putem elimina referințele la el dacă dorim
                pass

            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                
                is_qt_window_active = self.qt_app and self.qt_app.activeWindow() is not None
                if is_qt_window_active:
                    continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Acum se apelează direct handler-ul de joc
                    self._handle_game_mousedown(event.pos)
                
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if not self.current_state.is_recording and self.current_state.dragging_piece:
                        self._handle_game_mouseup(event.pos)
                
                elif event.type == pygame.MOUSEMOTION:
                    if not self.current_state.is_recording and self.current_state.dragging_piece:
                        self.current_state.drag_pos = event.pos

                elif event.type == pygame.KEYDOWN:
                     # Am scos verificarea pentru text input, deoarece a fost eliminată
                     pass


            # --- Randarea Pygame ---
            self.screen.fill((30, 30, 30))
            
            # Randăm direct ecranul de joc
            # --- AICI ESTE MODIFICAREA ---
            total_matching = self.total_matching_traps
            
            all_buttons = self.renderer.render_control_panel(self.screen, self.current_state, self.current_state.move_history)
            
            suggestion_buttons = self.renderer.render_suggestions_panel(
                self.screen, self.current_state, self.current_suggestions, total_matching
            )
            
            white_info, black_info = self.opening_db.get_opening_phase_info(
                self.current_state.board, 
                self.current_state.move_history
            )
            
            self.renderer.render_board(self.screen, self.current_state, self.flipped)
            self.renderer.render_pieces(
                self.screen, self.current_state.board, self.piece_loader,
                self.current_state.selected_square, self.flipped,
                self.current_state.dragging_piece, self.current_state.drag_pos
            )
            self.renderer.render_status(self.screen, self.current_state, white_info, black_info)

            pygame.display.flip()
            clock.tick(60)
        
        print("[DEBUG MAIN] Main loop ended")
        pygame.quit()
    
    def _start_game(self, color: chess.Color, is_recording: bool = False) -> None:
        """Starts a new game or a new recording session."""
        
        # Am mutat logica de `_start_recording` aici pentru a fi un singur punct de intrare
        if is_recording:
            print("[REC] New recording session started. Board is reset.")
        else:
            print(f"[DEBUG START] Starting new game as {chess.COLOR_NAMES[color]}.")

        self.current_state = GameState(
            board=chess.Board(),
            current_player=color,
            is_recording=is_recording
        )
        
        self.flipped = (color == chess.BLACK)
        self.move_history_forward = []
        
        if not is_recording:
            self._update_suggestions()
        else:
            self.current_suggestions = [] # Ascundem sugestiile în modul record

    def _start_recording(self):
            """Starts a new recording session by resetting the board and state."""
            print("[REC] New recording session started. Board is reset.")
            self.current_state = GameState(
                board=chess.Board(),
                current_player=self.current_state.current_player, # Păstrăm culoarea selectată
                is_recording=True,
                # Istoricele sunt goale la început
                move_history=[], 
                recording_history=[]
            )
            self.flipped = (self.current_state.current_player == chess.BLACK)
            self.move_history_forward = []
            self.current_suggestions = [] # Ascundem sugestiile
            self._clear_highlights()

    def _clear_database(self):
        """Handles clearing ALL traps from BOTH databases (PGN and custom) using a PostgreSQL backend."""
        if not QT_AVAILABLE:
            print("[DB] Cannot clear DB: Qt (PySide6) not available for confirmation dialog.")
            return
            
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Confirm Database Deletion")
        msg_box.setText("Are you sure you want to permanently delete ALL traps from the database?")
        msg_box.setInformativeText("This will affect both PGN-imported and manually recorded traps.\nThis action cannot be undone.")
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        
        response = msg_box.exec()
        
        if response == QMessageBox.StandardButton.Yes:
            print("[DB] User confirmed deletion. Clearing all trap tables...")
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_WAIT)
            try:
                # 1. Șterge datele din baza de date
                pgn_deleted_count = self.trap_repository.clear_all_traps()
                custom_deleted_count = self.queen_trap_repository.clear_all_traps()

                # --- AICI ESTE CORECȚIA ---
                # Definirea căilor către cache direct aici, fără a depinde de servicii.
                main_cache_path = "trap_index.cache"
                queen_cache_path = "queen_trap_index.cache"

                # 2. Invalidează cache-urile prin ștergerea fișierelor.
                if os.path.exists(main_cache_path):
                    os.remove(main_cache_path)
                    print(f"[CACHE] Removed main trap cache: {main_cache_path}")
                if os.path.exists(queen_cache_path):
                    os.remove(queen_cache_path)
                    print(f"[CACHE] Removed custom trap cache: {queen_cache_path}")
                
                # 3. Re-inițializează serviciile (chiar dacă nu mai încarcă mare lucru, e o bună practică)
                print("[SERVICE] Re-initializing services after database clear...")
                self.trap_service = TrapService(self.trap_repository)
                self.queen_trap_service = QueenTrapService(self.queen_trap_repository)
                
                # 4. Actualizează UI-ul.
                self._update_suggestions() 
                
                # 5. Arată mesajul de succes.
                total_deleted = pgn_deleted_count + custom_deleted_count
                success_msg = f"All {total_deleted} traps have been successfully cleared. Application data has been refreshed."
                QMessageBox.information(None, "Success", success_msg)
                print(f"[DB] {success_msg}")

            except Exception as e:
                error_msg = f"An unexpected error occurred while clearing the database: {e}"
                QMessageBox.critical(None, "Error", error_msg)
                print(f"[DB ERROR] {error_msg}")
            finally:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
        else:
            print("[DB] Deletion cancelled by user.")
    
    def _handle_game_mousedown(self, pos: Tuple[int, int]) -> None:
        """Handle mouse down events during main game."""
        
        # Colectăm TOATE butoanele active de pe ecran într-un singur loc
        all_button_rects = {}
        
        # 1. Butoanele din panoul de control (inclusiv noul "Copy PGN")
        # --- AICI ESTE CORECȚIA ---
        control_rects = self.renderer.render_control_panel(
            pygame.Surface((self.config.BUTTONS_WIDTH, self.config.HEIGHT)), 
            self.current_state, 
            self.current_state.move_history  # Am adăugat argumentul lipsă
        )
        all_button_rects.update(control_rects)
        
        # 2. Butoanele din panoul de sugestii
        total_matching = self.total_matching_traps
        suggestion_rects = self.renderer.render_suggestions_panel(
            pygame.Surface((self.config.SUGGESTIONS_WIDTH, self.config.HEIGHT)),
            self.current_state,
            self.current_suggestions, 
            total_matching
        )
        all_button_rects.update(suggestion_rects)

        # Verificăm dacă s-a dat click pe vreun buton
        action = self.input_handler.handle_button_click(pos, all_button_rects)
        
        if action:
            # Tratăm acțiunile de la butoane, inclusiv "copy_pgn"
            if action == "copy_pgn":
                history_text = ""
                for i, move in enumerate(self.current_state.move_history):
                    if i % 2 == 0:
                        history_text += f"{i//2 + 1}. {move} "
                    else:
                        history_text += f"{move} "
                
                pyperclip.copy(history_text.strip())
                print(f"[CLIPBOARD] Copiat: {history_text.strip()}")
            else:
                # Tratăm celelalte acțiuni
                print(f"[DEBUG] Button action: {action}")
                self._handle_action(action)
        else:
            # Dacă nu s-a dat click pe niciun buton, verificăm tabla de șah
            self._handle_board_mousedown(pos)
    
    def _handle_game_mouseup(self, pos: Tuple[int, int]) -> None:
        """Handle mouse up events during main game."""
        if self.current_state.dragging_piece:
            # Complete the drag operation
            self._handle_board_mouseup(pos)
    
    def _handle_board_mousedown(self, pos: Tuple[int, int]) -> None:
        """Handle mouse down on the chess board."""
        square = self.input_handler.get_square_from_mouse(pos, self.flipped)
        if square is None:
            if self.current_state.selected_square is not None:
                 # Dacă am dat click în afara tablei, deselectăm piesa
                 self.current_state.selected_square = None
                 print("[DEBUG] Piece deselected.")
            return
        
        # --- Logica pentru modul de înregistrare (corectată) ---
        if self.current_state.is_recording:
            if self.current_state.selected_square is None:
                # Primul click: selectăm piesa
                piece = self.current_state.board.piece_at(square)
                if piece and piece.color == self.current_state.board.turn:
                    self.current_state.selected_square = square
                    self.current_state.dragging_piece = piece # Setăm și pentru drag-and-drop
                    self.current_state.drag_pos = pos
            else:
                # Al doilea click: încercăm să facem mutarea
                self._try_make_move(self.current_state.selected_square, square)
            return

        # --- Logica pentru jocul normal (neschimbată) ---
        if self.current_state.selected_square is None:
            piece = self.current_state.board.piece_at(square)
            if piece and piece.color == self.current_state.board.turn:
                print(f"[DEBUG] Starting drag of {piece} at {chess.square_name(square)}. Active line is: {self.current_state.active_trap_line}")
                self.current_state.selected_square = square
                self.current_state.dragging_piece = piece
                self.current_state.drag_pos = pos
        else:
            self._try_make_move(self.current_state.selected_square, square)

    def _handle_board_mouseup(self, pos: Tuple[int, int]) -> None:
        """Handle mouse up on the chess board to complete a move."""
        if not self.current_state.dragging_piece or self.current_state.selected_square is None:
            return
        
        target_square = self.input_handler.get_square_from_mouse(pos, self.flipped)
        
        if target_square is not None:
            self._try_make_move(self.current_state.selected_square, target_square)
        else:
            # Dropped outside board, just deselect
            print("[DEBUG] Piece dropped outside board.")
        
        # Indiferent dacă mutarea a fost validă sau nu, oprim drag-ul.
        # _make_move se ocupă de asta dacă mutarea e validă, dar adăugăm
        # o siguranță aici pentru cazul în care nu este.
        self.current_state.selected_square = None
        self.current_state.dragging_piece = None
        self.current_state.drag_pos = None
    
    def _try_make_move(self, from_square: chess.Square, to_square: chess.Square) -> None:
        """Try to make a move from one square to another."""
        move = chess.Move(from_square, to_square)
        
        # Handle pawn promotion
        piece = self.current_state.board.piece_at(from_square)
        if (piece and piece.piece_type == chess.PAWN and 
            chess.square_rank(to_square) in [0, 7]):
            move.promotion = chess.QUEEN
        
        if move in self.current_state.board.legal_moves:
            print(f"[DEBUG] Making move: {move}")
            self._make_move(move)
        else:
            print(f"[DEBUG] Illegal move: {move}")
    
    def _clear_highlights(self):
        """Resets only the visual highlights on the board."""
        self.current_state.highlighted_squares = None
        self.current_state.highlight_color = None

    def _handle_board_click(self, pos: Tuple[int, int]) -> None:
        """Handle clicks on the chess board (legacy method - kept for compatibility)."""
        # This method is now replaced by _handle_board_mousedown and _handle_board_mouseup
        # but kept here in case it's called from somewhere else
        self._handle_board_mousedown(pos)
    
    def _make_move(self, move: chess.Move) -> None:
        """Applies a move to the board and updates game state."""
        
        # --- ADAUGAȚI ACEST BLOC DE MĂSURARE ---
        import time
        start_time = time.time()
        # ----------------------------------------

        # Calculăm SAN-ul înainte de a modifica tabla
        move_san = self.current_state.board.san(move)
        
        # Aplicăm mutarea pe tablă
        self.current_state.board.push(move)
        
        # Resetăm starea de UI
        self.current_state.selected_square = None
        self.current_state.dragging_piece = None
        
        if self.current_state.is_recording:
            # În modul de înregistrare, adăugăm la ambele istorice
            self.current_state.recording_history.append(move_san)
            self.current_state.move_history.append(move_san) # Corecția este aici!
            print(f"[REC] Move {len(self.current_state.recording_history)}: {move_san}")
            return # Ne oprim aici

        # --- Logica pentru modul de joc normal ---
        moving_color = not self.current_state.board.turn # Culoarea care tocmai a mutat
        move_san_clean = move_san.replace('+', '').replace('#', '')
        active_trap_line = self.current_state.active_trap_line
        
        self.current_state.move_history.append(move_san)
        self.move_history_forward = []
        
        self._clear_highlights()
        
        if moving_color == self.current_state.current_player:
            self.current_suggestions = []
            self.current_state.trap_success_message = None

            if active_trap_line:
                expected_move_clean = active_trap_line[0].replace('+', '').replace('#', '')
                if move_san_clean == expected_move_clean:
                    if len(active_trap_line) == 1:
                        self.current_state.trap_success_message = "Trap Successful!\nOpponent's position is lost."
                        self.current_state.active_trap_line = None
                        print("[DEBUG] TRAP COMPLETE!")
                    else:
                        try:
                            opponent_response_san = active_trap_line[1]
                            opponent_move = self.current_state.board.parse_san(opponent_response_san)
                            self.current_state.highlighted_squares = (opponent_move.from_square, opponent_move.to_square)
                            self.current_state.highlight_color = self.config.HIGHLIGHT_GREEN
                            print(f"[DEBUG] Following trap. Highlighting: {opponent_response_san}")
                        except Exception as e:
                            print(f"[ERROR] Could not highlight next move: {e}")
                            self.current_state.active_trap_line = None
                else:
                    self.current_state.active_trap_line = None
        
        else: # Rândul adversarului
            if active_trap_line and len(active_trap_line) > 1:
                expected_opponent_move_clean = active_trap_line[1].replace('+', '').replace('#', '')
                if move_san_clean == expected_opponent_move_clean:
                    self.current_state.active_trap_line = active_trap_line[2:]
                else:
                    self.current_state.active_trap_line = None
            else:
                self.current_state.active_trap_line = None
            
            self._update_suggestions()
        
        # --- ADAUGAȚI ACEST BLOC DE MĂSURARE ---
        end_time = time.time()
        print(f"[TIMING] Durata totală a logicii _make_move: {end_time - start_time:.4f} secunde")
        # ----------------------------------------
        
    def _update_suggestions(self) -> None:
        if self.current_state.board.turn != self.current_state.current_player or self.current_state.is_recording:
            self.current_suggestions = []
            self.total_matching_traps = 0
            return

        import time
        total_start_time = time.time()
        
        # Măsurăm sugestiile de șah-mat (PostgreSQL)
        t0 = time.time()
        # MODIFICARE: Acum primim și numărul total de potriviri direct
        checkmate_suggs, total_checkmates = self.trap_service.get_aggregated_suggestions(self.current_state)
        t1 = time.time()
        print(f"[TIMING] Obținere sugestii Checkmate (DB): {t1 - t0:.4f} secunde")

        # Măsurăm sugestiile custom (din memorie) - rămâne la fel
        t0 = time.time()
        custom_suggs = self.queen_trap_service.get_aggregated_suggestions(self.current_state)
        t1 = time.time()
        print(f"[TIMING] Obținere sugestii Custom (Memorie): {t1 - t0:.4f} secunde")
        
        # Măsurăm logica de sortare și numărare (acum mult mai rapidă)
        t0 = time.time()
        all_suggs = checkmate_suggs + custom_suggs
        all_suggs.sort(key=lambda s: (s.trap_type == 'checkmate', -s.trap_count))
        self.current_suggestions = all_suggs
        
        # MODIFICARE: Nu mai interogăm DB a doua oară!
        # Folosim valorile deja obținute.
        total_customs = self.queen_trap_service.count_matching_traps(self.current_state)
        self.total_matching_traps = total_checkmates + total_customs
        t1 = time.time()
        print(f"[TIMING] Procesare finală (Sortare + Numărare): {t1 - t0:.4f} secunde")

        total_end_time = time.time()
        print(f"[TIMING] Durata totală a _update_suggestions: {total_end_time - total_start_time:.4f} secunde")

        print(f"[DEBUG] Updated suggestions. Unique moves: {len(all_suggs)}. Total matching lines: {self.total_matching_traps}")

    def _manage_queen_traps(self):
        """Opens the Queen Trap management dialog."""
        if not QT_AVAILABLE:
            print("[MANAGE] Cannot manage traps: PySide6 (Qt) is not available.")
            return

        def on_trap_deleted_callback():
            print("[CONTROLLER] A custom trap was deleted. Forcing fast-cache service reload.")
            self.queen_trap_service.force_reload()
            self._update_suggestions()

        # --- MODIFICAREA AICI ---
        # Pasăm și noul callback `on_trap_load`.
        dialog = QtQueenTrapManager(
            self.queen_trap_repository, 
            on_trap_deleted_callback,
            on_trap_load=self.load_moves_onto_board # Aici conectăm metoda
        )
        dialog.exec()
    
    def _update_game_state(self) -> None:
        """Update game state each frame."""
        # Handle text input for recording
        if self.current_state.is_recording:
            # Check for Enter key to stop recording
            keys = pygame.key.get_pressed()
            if keys[pygame.K_RETURN]:
                self._stop_recording()

    def _select_suggestion(self, suggestion: MoveSuggestion):
        """Highlights the board based on a selected suggestion without making a move."""
        try:
            move = self.current_state.board.parse_san(suggestion.suggested_move)
            
            self.current_state.highlighted_squares = (move.from_square, move.to_square)
            self.current_state.highlight_color = self.config.HIGHLIGHT_RED
            
            # Salvăm linia de capcană pe care intenționăm să o urmăm
            self.current_state.active_trap_line = suggestion.example_trap_line
            
            print(f"[DEBUG] Suggestion '{suggestion.suggested_move}' selected. Highlighting in red.")

        except ValueError:
            print(f"[DEBUG] Error parsing suggested move SAN: {suggestion.suggested_move}")
            self._clear_highlights()

    def _go_to_start(self) -> None:
        """Go to the beginning of the game, effectively resetting it."""
        print("[DEBUG] 'Go to Start' pressed, resetting the game.")
        # Acum, această metodă resetează complet jocul.
        self._start_game(self.current_state.current_player)

    def _handle_action(self, action: str) -> None:
        """Handle various game actions based on the desired workflow."""

        # --- Logica pentru butonul "Record" ---
        # Aceasta este singura funcție a acestui buton.
        if action == "record":
            # Indiferent de starea curentă, încercăm să salvăm istoricul.
            # Nu mai avem un "mod de înregistrare" separat.
            print("[ACTION] 'Record' button pressed. Attempting to save current game line...")
            self._handle_stop_recording_request(self.current_state.move_history)
            return

        # --- Logica pentru butoanele de navigație și setări ---
        # Aceste acțiuni sunt acum independente de "record".
        
        if action == "play_as_white":
            self._start_game(chess.WHITE)
        elif action == "play_as_black":
            self._start_game(chess.BLACK)
        elif action == "db_info":
            self._show_database_info()
        elif action == "to_start":
            self._go_to_start()
        elif action == "one_back":
            self._go_back_one()
        elif action == "one_forward":
            self._go_forward_one()
        elif action == "to_end":
            self._go_to_end()
        elif action == "import_pgn":
            self._import_pgn_file()
        elif action.startswith("suggestion_"):
            idx = int(action.split("_")[1])
            if 0 <= idx < len(self.current_suggestions):
                self._select_suggestion(self.current_suggestions[idx])
        
        # Am eliminat complet acțiunea "reset_game" / "main_menu"

    def _handle_stop_recording_request(self, moves_to_analyze: List[str]):
        """
        Handles a request to save a line, using the provided move list.
        This method NEVER resets the board.
        """
        if not moves_to_analyze:
            print("[REC] No moves to save. The game history is empty.")
            if QT_AVAILABLE:
                QMessageBox.information(None, "Nothing to Record", "Play some moves first before recording a trap.")
            return

        detected_type, winning_color = self._analyze_recorded_line(moves_to_analyze)

        decision = None
        if QT_AVAILABLE:
            decision = QtSaveConfirmDialog.get_decision(detected_type, moves_to_analyze)
        else:
            # Fallback pentru testare fără Qt
            decision = QtSaveConfirmDialog.SAVE

        if decision == QtSaveConfirmDialog.SAVE:
            print("[REC] User chose to save the trap.")
            self._save_trap_logic(detected_type, winning_color, moves_to_analyze)
            # După salvare, actualizăm sugestiile pentru poziția curentă.
            # Asta e tot, nicio resetare.
            self._update_suggestions()
            
        elif decision == QtSaveConfirmDialog.CANCEL:
            print("[REC] Save action cancelled by user. Game continues.")
            # Nu facem absolut nimic, jocul continuă normal.
            
        elif decision == QtSaveConfirmDialog.CONTINUE:
            print("[REC] Save dialog 'Continue' selected. Game continues.")
            # Nici aici nu facem nimic, jocul continuă normal.

    def _go_back_one(self) -> None:
        """Go back one move in the current game history."""
        if self.current_state.move_history:
            self.current_state.board.pop()
            self.move_history_forward.insert(0, self.current_state.move_history.pop())
            self._clear_highlights()
            self._update_suggestions()

    def _go_forward_one(self) -> None:
        """Go forward one move if available."""
        if self.move_history_forward:
            next_move_san = self.move_history_forward.pop(0)
            try:
                move = self.current_state.board.parse_san(next_move_san)
                # Re-folosim _make_move pentru a menține consistența stării
                self._make_move(move)
            except ValueError:
                # Dacă mutarea e invalidă, o punem la loc pentru a nu o pierde
                self.move_history_forward.insert(0, next_move_san)
 
    def _go_to_end(self) -> None:
        """Go to the end of the game (the last known position)."""
        while self.move_history_forward:
            self._go_forward_one()
        
        # Asigură-te că și la final, orice highlight este curățat
        self._clear_highlights()

    def _analyze_recorded_line(self, moves_san: List[str]) -> Tuple[str, Optional[chess.Color]]:
        board = chess.Board()
        last_move_obj = None
        try:
            for move_san in moves_san:
                clean_san = move_san.replace('#', '').replace('+', '')
                last_move_obj = board.parse_san(clean_san)
                board.push(last_move_obj)
        except ValueError as e:
            print(f"[ANALYZE ERROR] Failed to parse sequence: {e}")
            return "Invalid Move Sequence", None

        # De aici, restul metodei rămâne la fel...
        if board.is_checkmate():
            return "Checkmate", not board.turn

        board_before_last = board.copy()
        board_before_last.pop()
        captured = board_before_last.piece_at(last_move_obj.to_square)
        if captured and captured.piece_type == chess.QUEEN:
            return "Direct Queen Capture", board_before_last.turn

        attacker_square = last_move_obj.to_square
        attacker_piece = board.piece_at(attacker_square)
        if attacker_piece:
            opponent_color = not attacker_piece.color
            king_sq = board.king(opponent_color)
            queen_sq_set = board.pieces(chess.QUEEN, opponent_color)
            if king_sq and queen_sq_set:
                queen_sq = queen_sq_set.pop()
                is_fork = attacker_square in board.attackers(attacker_piece.color, king_sq) and \
                          attacker_square in board.attackers(attacker_piece.color, queen_sq)
                if is_fork:
                    return "Royal Fork", attacker_piece.color

        return "Standard Line", None
    
    def _save_trap_logic(self, detected_type: str, winning_color: Optional[chess.Color], moves: List[str]):
        """
        Saves ANY manually recorded trap (checkmate or queen loss) to the
        'custom traps' system (originally the queen trap system) for fast,
        non-blocking performance.
        """
        if winning_color is None or detected_type == "Standard Line":
            print("[DB] Line not saved as it's not a recognized trap type.")
            if QT_AVAILABLE:
                QMessageBox.information(None, "Not Saved", "The recorded line is not a recognized trap type.")
            return

        # Toate capcanele custom, indiferent de tip, merg în sistemul 'queen_traps' (cel rapid)
        trap_name = f"{detected_type.replace(' ', '')} ({moves[0]}...)"
        
        # Pentru 'capture_square', folosim o valoare generică (0) dacă e mat,
        # altfel calculăm pătrățelul reginei.
        capture_square = 0 
        if detected_type in ["Direct Queen Capture", "Royal Fork"]:
            final_board = chess.Board()
            for move_san in moves: 
                # Parsăm o versiune curată a mutării
                clean_san = move_san.replace('#','').replace('+','')
                final_board.push(final_board.parse_san(clean_san))
            
            opponent_color = not winning_color
            queen_square_set = final_board.pieces(chess.QUEEN, opponent_color)
            if queen_square_set:
                capture_square = queen_square_set.pop()

        # Creăm obiectul cu noul câmp `trap_type`
        new_custom_trap = QueenTrap(
            name=trap_name, 
            trap_type=detected_type, # Salvăm tipul real detectat
            moves=moves, 
            color=winning_color, 
            capture_square=capture_square
        )
        
        # Salvăm în repository-ul rapid (queen_trap_repository)
        trap_id = self.queen_trap_repository.save_trap(new_custom_trap)
        
        if trap_id != -1: # Verificăm dacă nu a fost un duplicat
            new_custom_trap.id = trap_id
            # Forțăm reîncărcarea serviciului rapid (queen trap service), care este instantaneu
            self.queen_trap_service.force_reload()
            print(f"[DB] Saved custom trap '{trap_name}' to the fast index.")
            if QT_AVAILABLE:
                QMessageBox.information(None, "Success", f"Successfully saved custom trap: {detected_type}")
        else:
            if QT_AVAILABLE:
                QMessageBox.warning(None, "Duplicate", "This exact trap line already exists in your custom traps.")

    def _import_pgn_file(self) -> None:
        """Opens the Qt Import Settings window."""
        if not QT_AVAILABLE:
            print("[IMPORT] Cannot import: PySide6 (Qt) is not available.")
            return

        def handle_file_import(filepath, max_moves, checkmate_only):
            print(f"[IMPORT] Starting import for single file...")
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_WAIT)
            
            total, white, black = self.pgn_service.import_from_file(filepath, max_moves, checkmate_only)
            
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            
            success_message = (
                f"File import complete!\n\n"
                f"Total new unique traps added:\n"
                f"- {white} white traps\n"
                f"- {black} black traps\n\n"
                f"Total: {total}"
            )
            QMessageBox.information(None, "Import Complete", success_message)

        def handle_folder_import(folderpath, max_moves, checkmate_only):
            print(f"[IMPORT] Starting import for folder...")
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_WAIT)
            
            total, white, black = self.pgn_service.import_from_folder(folderpath, max_moves, checkmate_only)
            
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            
            success_message = (
                f"Folder import complete!\n\n"
                f"Total new unique traps added to database:\n"
                f"- {white} white traps\n"
                f"- {black} black traps\n\n"
                f"Total: {total}"
            )
            QMessageBox.information(None, "Folder Import Complete", success_message)

        dialog = QtImportWindow(
            self.settings_service, 
            on_start_file_import=handle_file_import, 
            on_start_folder_import=handle_folder_import,
            on_clear_db=self._clear_database,
            on_start_audit=self._run_database_audit,
            on_manage_queen_traps=self._manage_queen_traps,
            on_export_db=self._export_pgn_database
        )
        dialog.exec()
 
    def _export_pgn_database(self):
        """Handles the logic for exporting the main checkmate traps database to a PGN file."""
        if not QT_AVAILABLE:
            print("[EXPORT] Cannot export: PySide6 (Qt) is not available.")
            return

        # ... (codul pentru a întreba utilizatorul unde să salveze fișierul rămâne la fel)
        default_filename = f"chess_traps_export_{time.strftime('%Y%m%d')}.pgn"
        filepath, _ = QFileDialog.getSaveFileName(None, "Save Traps Database as PGN", default_filename, "PGN Files (*.pgn)")

        if filepath:
            print(f"[EXPORT] Initiating database export to PGN file: {filepath}")
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_WAIT)
            try:
                # Apelăm noua metodă eficientă
                exported_count = self.pgn_service.export_db_to_pgn_file(filepath)
                
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                QMessageBox.information(None, "Export Successful", f"Successfully exported {exported_count} traps to:\n{filepath}")
            except Exception as e:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                QMessageBox.critical(None, "Export Error", f"An unexpected error occurred during export: {e}")
                print(f"[EXPORT ERROR] {e}")
        else:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            print("[EXPORT] Export cancelled by user.")

    def _run_database_audit(self, max_moves: int):
        """Orchestrates the database audit and refreshes the application state ONLY if changes were made."""
        print("[CONTROLLER] Starting database audit process...")
        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_WAIT)

        # 1. Creează și rulează auditorul
        auditor = DatabaseAuditor(self.trap_repository)
        report, changes_were_made = auditor.run_audit(max_moves)
        
        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)

        # 2. Afișează raportul
        QMessageBox.information(self.qt_app.activeWindow(), "Audit Report", report)
        
        # 3. CRUCIAL: Reîmprospătează datele aplicației DOAR DACĂ A FOST NECESAR
        if changes_were_made:
            print("[CONTROLLER] Audit made changes. Refreshing TrapService and suggestions...")
            
            # Șterge fișierul cache dacă există, forțând reconstruirea lui
            if os.path.exists(TrapService.CACHE_FILE_PATH):
                try:
                    os.remove(TrapService.CACHE_FILE_PATH)
                    print("[CONTROLLER] Removed stale cache file.")
                except OSError as e:
                    print(f"[CONTROLLER] Error removing cache file: {e}")

            # Re-inițializează serviciul pentru a încărca datele curate
            self.trap_service = TrapService(self.trap_repository)
            self._update_suggestions()
            
            QMessageBox.information(self.qt_app.activeWindow(), "Success", "Database was modified. Application data has been refreshed.")
        else:
            print("[CONTROLLER] Audit found no issues. No refresh needed.")
            QMessageBox.information(self.qt_app.activeWindow(), "Success", "Database is clean. No changes were made.")

    def _show_database_info(self):
        """Collects and displays detailed database statistics in a Qt dialog."""
        if not QT_AVAILABLE:
            pgn_traps = self.trap_repository.get_total_trap_count()
            custom_traps = self.queen_trap_repository.get_total_trap_count()
            print(f"PGN Checkmate Traps: {pgn_traps}, Manually Recorded Traps: {custom_traps}")
            return

        # Colectează datele
        pgn_checkmates = self.trap_repository.get_total_trap_count()
        # Aici apelăm noua metodă pentru a obține detaliile pe culori
        white_traps, black_traps = self.trap_repository.get_trap_counts_by_color()
        
        all_custom_traps = self.queen_trap_repository.get_all_traps()
        manually_recorded = len(all_custom_traps)
        
        recorded_mates_count = sum(1 for trap in all_custom_traps if trap.trap_type == 'Checkmate')
        queen_hunt_count = manually_recorded - recorded_mates_count
        
        total_traps = pgn_checkmates + manually_recorded
        
        # Construim dicționarul pentru afișare, adăugând noile linii
        stats = {
            "PGN Checkmate Library": f"{pgn_checkmates:,}",
            "   - White Traps": f"{white_traps:,}",
            "   - Black Traps": f"{black_traps:,}",
            "separator1": "", 
            "Manually Recorded Traps": f"{manually_recorded:,}",
            "   - Queen Hunts / Forks": f"{queen_hunt_count:,}",
            "   - Checkmates": f"<b>{recorded_mates_count:,}</b>",
            "separator2": "",
            "Total Unique Traps": f"<b>{total_traps:,}</b>"
        }
        
        # Creează și afișează dialogul
        dialog = QtInfoDialog(
            stats,
            on_export_pgn=self._handle_export_custom_checkmates,
            on_delete_custom_mates=self._handle_delete_custom_checkmates
        )
        dialog.exec()

    def _handle_export_custom_checkmates(self):
        """Exports all manually recorded checkmates to a PGN file."""
        all_custom_traps = self.queen_trap_repository.get_all_traps()
        
        # Filtrăm doar capcanele de mat
        checkmates_to_export = [trap for trap in all_custom_traps if trap.trap_type == 'Checkmate']
        
        if not checkmates_to_export:
            QMessageBox.information(None, "No Checkmates", "No manually recorded checkmates found to export.")
            return

        # Pregătim datele pentru PGN
        pgn_string = ""
        game_database = chess.pgn.Game()
        
        for i, trap in enumerate(checkmates_to_export):
            game = chess.pgn.Game()
            game.headers["Event"] = "Custom Checkmate Export"
            game.headers["Site"] = "Chess Trap Explorer"
            game.headers["Date"] = time.strftime("%Y.%m.%d")
            game.headers["Round"] = str(i + 1)
            game.headers["White"] = "Player" if trap.color == chess.WHITE else "Opponent"
            game.headers["Black"] = "Player" if trap.color == chess.BLACK else "Opponent"
            game.headers["Result"] = "1-0" if trap.color == chess.WHITE else "0-1"
            
            board = chess.Board()
            node = game
            for move_san in trap.moves:
                try:
                    move = board.parse_san(move_san)
                    node = node.add_variation(move)
                    board.push(move)
                except ValueError:
                    print(f"Skipping invalid move '{move_san}' in trap {trap.name}")
                    continue
            
            pgn_string += str(game) + "\n\n"

        # Deschidem dialogul de salvare fișier
        filepath, _ = QFileDialog.getSaveFileName(None, "Save Custom Checkmates PGN", "", "PGN Files (*.pgn)")

        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(pgn_string)
                QMessageBox.information(None, "Success", f"Successfully exported {len(checkmates_to_export)} checkmates to:\n{filepath}")
            except Exception as e:
                QMessageBox.critical(None, "Error", f"Failed to save the file: {e}")

    def _handle_delete_custom_checkmates(self):
        """Handles the deletion of manually recorded checkmates after user confirmation."""
        reply = QMessageBox.question(None, "Confirm Deletion",
                                     "Are you sure you want to delete all manually recorded checkmates?\n\nThis action cannot be undone. Make sure you have exported and imported them first.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = self.queen_trap_repository.delete_checkmate_traps()
            
            if deleted_count > 0:
                # CRUCIAL: Reîmprospătăm serviciul și sugestiile
                self.queen_trap_service.force_reload()
                self._update_suggestions()
                QMessageBox.information(None, "Success", f"Successfully deleted {deleted_count} custom checkmate traps.")
                # Închidem fereastra de statistici pentru a forța redeschiderea cu date actualizate
                if self.qt_app.activeWindow():
                    self.qt_app.activeWindow().accept()
            else:
                QMessageBox.information(None, "No Action", "No custom checkmates were found to delete.")

    def load_moves_onto_board(self, moves_san: List[str]):
        """
        Clears the current game and loads a new sequence of moves onto the board.
        This effectively starts a new game from the provided line.
        """
        print(f"[ACTION] Loading a new line onto the board: {' '.join(moves_san)}")
        
        # Începem un joc nou pentru a ne asigura că totul este curat
        self._start_game(self.current_state.current_player)
        
        board = self.current_state.board
        temp_history = []
        
        for move_san in moves_san:
            try:
                clean_san = move_san.replace('#', '').replace('+', '')
                move = board.parse_san(clean_san)
                board.push(move)
                temp_history.append(move_san)
            except ValueError as e:
                print(f"[LOAD ERROR] Could not parse move '{move_san}'. Stopping load. Error: {e}")
                QMessageBox.warning(None, "Load Error", f"Could not load the full line. Invalid move found: {move_san}")
                break # Ne oprim dacă o mutare este invalidă

        # Actualizăm starea jocului cu noua linie
        self.current_state.move_history = temp_history
        self.move_history_forward = [] # Nu există mutări "forward"
        
        # Curățăm highlight-urile și actualizăm sugestiile pentru noua poziție
        self._clear_highlights()
        self._update_suggestions()
        print("[ACTION] Board position updated successfully.")

def main():
    """Main entry point."""
    # --- CONFIGURARE LOGGING CU TIMESTAMP ---
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # ----------------------------------------
    
    try:
        controller = GameController()
        controller.run()
    except Exception as e:
        logging.error(f"[ERROR] Application error: {e}", exc_info=True)

if __name__ == "__main__":
    main()