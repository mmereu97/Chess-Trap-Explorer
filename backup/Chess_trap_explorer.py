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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Protocol
from pathlib import Path
from collections import defaultdict  # <--- ADAUGĂ ACEASTĂ LINIE AICI
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count


# Import tkinter with error handling
try:
    from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QPushButton, 
                                   QLabel, QLineEdit, QCheckBox, QProgressBar, 
                                   QMessageBox, QFileDialog, QVBoxLayout, 
                                   QHBoxLayout, QGroupBox, QFrame)
    from PySide6.QtCore import Qt
    QT_AVAILABLE = True
    print("[DEBUG INIT] PySide6 (Qt) imported successfully.")
except ImportError:
    QT_AVAILABLE = False
    print("[DEBUG INIT] PySide6 (Qt) not available - import functionality will be limited.")



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
    # Tabla trebuie să fie cel mai mare pătrat posibil, multiplu de 8.
    # Înălțimea disponibilă este ~720px. Lățimea: 1280 - 200 - 340 = 740px.
    # O valoare bună, mai mică de 720, este 576.
    BOARD_SIZE: int = 576 # 576 este 72 * 8. Este o valoare excelentă.
    SQUARE_SIZE: int = BOARD_SIZE // 8  # 72px per pătrățel
    
    # --- Margini ---
    TOP_MARGIN: int = 40
    LEFT_MARGIN: int = BUTTONS_WIDTH + 40 # Spațiu redus proporțional -> 240
    
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
    # Stocăm o linie exemplu pentru a ști ce mutare așteptăm de la adversar
    example_trap_line: List[str]

@dataclass
class GameState:
    """Represents the current state of the chess game."""
    board: chess.Board
    current_player: chess.Color
    is_recording: bool = False
    move_history: List[str] = field(default_factory=list)
    selected_square: Optional[chess.Square] = None
    dragging_piece: Optional[chess.Piece] = None
    drag_pos: Optional[Tuple[int, int]] = None
    
    # NOU: Câmpuri pentru colorarea pătrățelelor
    highlighted_squares: Optional[Tuple[chess.Square, chess.Square]] = None
    highlight_color: Optional[Tuple[int, int, int, int]] = None
    
    # NOU: Câmp pentru a reține ce linie de capcană a ales utilizatorul
    active_trap_line: Optional[List[str]] = None

# Repository Layer

class TrapRepository:
    """Repository for managing chess traps in SQLite database."""
    
    def __init__(self, db_path: str = "chess_traps.db"):
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize the database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    moves TEXT NOT NULL,
                    color INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    
    def save_trap(self, trap: ChessTrap) -> int:
        """Save a trap to the database and return its ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO traps (name, moves, color) VALUES (?, ?, ?)",
                (trap.name, json.dumps(trap.moves), int(trap.color))
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_all_traps(self) -> List[ChessTrap]:
        """Get all traps from database."""
        traps = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT id, name, moves, color FROM traps")
                for row in cursor.fetchall():
                    trap_id, name, moves_json, color = row
                    moves = json.loads(moves_json)
                    traps.append(ChessTrap(id=trap_id, name=name, moves=moves, color=bool(color)))
        except sqlite3.Error as e:
            print(f"[DB ERROR] Could not read traps: {e}")
        return traps
    
    def get_total_trap_count(self) -> int:
        """Get total number of traps in database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM traps")
                return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0
            
    def import_traps(self, traps: List[ChessTrap]) -> int:
        """Import multiple traps, avoiding duplicates."""
        imported_count = 0
        
        with sqlite3.connect(self.db_path) as conn:
            for trap in traps:
                # Check for duplicates (same color and moves)
                cursor = conn.execute(
                    "SELECT id FROM traps WHERE color = ? AND moves = ?",
                    (int(trap.color), json.dumps(trap.moves))
                )
                
                if not cursor.fetchone():  # No duplicate found
                    trap_id = self.save_trap(trap)
                    imported_count += 1
                    print(f"[DEBUG DB] Salvat: {trap.name} (ID: {trap_id})")
                else:
                    print(f"[DEBUG DB] Duplicat găsit, sărim: {trap.name}")
        
        return imported_count

    # --- METODE NOI PENTRU AUDIT ---
    
    def delete_traps_by_ids(self, ids: List[int]):
        """Deletes multiple traps from the database in a single transaction."""
        if not ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            # Create a placeholder string like (?, ?, ?) for the number of IDs
            placeholders = ', '.join('?' for _ in ids)
            query = f"DELETE FROM traps WHERE id IN ({placeholders})"
            conn.execute(query, ids)
            conn.commit()
            
    def update_trap_colors(self, updates: List[Tuple[bool, int]]):
        """Batch updates the color of multiple traps."""
        if not updates:
            return
        # `updates` is a list of (new_color, trap_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("UPDATE traps SET color = ? WHERE id = ?", updates)
            conn.commit()

    def get_trap_counts_by_color(self) -> Tuple[int, int]:
        """Returns the number of traps for White and Black."""
        white_count = 0
        black_count = 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                # chess.WHITE este True (1), chess.BLACK este False (0)
                cursor = conn.execute("SELECT color, COUNT(*) FROM traps GROUP BY color")
                for color, count in cursor.fetchall():
                    if color == 1: # White
                        white_count = count
                    else: # Black
                        black_count = count
        except sqlite3.Error as e:
            print(f"[DB ERROR] Could not get trap counts: {e}")
        return white_count, black_count

# Service Layer
class TrapService:
    """
    Service for managing trap logic and suggestions using position-based indexing
    with on-disk caching for fast startup.
    """
    
    # Definim calea către fișierul de cache
    CACHE_FILE_PATH = "trap_index.cache"
    
    def __init__(self, repository: TrapRepository):
        self.repository = repository
        print("[TRAP SERVICE] Initializing...")
        start_time = time.time()
        
        # 1. Încărcăm toate capcanele
        self.all_traps = self.repository.get_all_traps()
        self.id_to_trap_map = {trap.id: trap for trap in self.all_traps}
        
        # 2. Încercăm să încărcăm indexul din cache
        if not self._load_index_from_cache():
            # Dacă încărcarea eșuează sau cache-ul este invalid, construim indexul
            print("[TRAP SERVICE] Cache not found or invalid. Building new position index...")
            self.position_index = self._create_position_index()
            # Și îl salvăm pentru data viitoare
            self._save_index_to_cache()
        
        end_time = time.time()
        print(f"[TRAP SERVICE] Initialization complete in {end_time - start_time:.4f} seconds.")
        if self.all_traps:
            # --- AICI ESTE MODIFICAREA ---
            trap_count_formatted = f"{len(self.all_traps):_}".replace("_", " ")
            position_count_formatted = f"{len(self.position_index):_}".replace("_", " ")
            print(f"               Using index for {trap_count_formatted} traps across {position_count_formatted} unique positions.")

    def _load_index_from_cache(self) -> bool:
        """
        Tries to load the position index from a cache file.
        Returns True if successful and the cache is valid, False otherwise.
        """
        if not os.path.exists(self.CACHE_FILE_PATH):
            print("[TRAP SERVICE] Cache file not found.")
            return False
            
        try:
            with open(self.CACHE_FILE_PATH, 'rb') as f:
                print(f"[TRAP SERVICE] Reading cache file: {self.CACHE_FILE_PATH}")
                cache_data = pickle.load(f)
            
            cached_trap_count = cache_data['trap_count']
            cached_id_sum = cache_data['id_sum']
            
            # Validarea cache-ului
            current_trap_count = len(self.all_traps)
            current_id_sum = sum(trap.id for trap in self.all_traps if trap.id is not None)
            
            if current_trap_count == cached_trap_count and current_id_sum == cached_id_sum:
                # Cache-ul este valid! Îl folosim.
                self.position_index = cache_data['index']
                print("[TRAP SERVICE] Cache is valid and loaded successfully.")
                return True
            else:
                # Cache-ul este invalid (datele din DB s-au schimbat)
                print("[TRAP SERVICE] Cache is stale. DB has changed.")
                return False
                
        except (pickle.UnpicklingError, KeyError, EOFError) as e:
            # Fișierul de cache este corupt sau are un format vechi
            print(f"[TRAP SERVICE] Cache file is corrupt or invalid: {e}. It will be rebuilt.")
            return False

    def _save_index_to_cache(self) -> None:
        """
        Saves the current position index and validation data to the cache file.
        """
        if not hasattr(self, 'position_index') or not self.position_index:
            print("[TRAP SERVICE] Index is empty, not saving cache.")
            return
            
        print(f"[TRAP SERVICE] Saving new index to cache file: {self.CACHE_FILE_PATH}")
        
        cache_data = {
            'trap_count': len(self.all_traps),
            'id_sum': sum(trap.id for trap in self.all_traps if trap.id is not None),
            'index': self.position_index
        }
        
        try:
            with open(self.CACHE_FILE_PATH, 'wb') as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
            print("[TRAP SERVICE] Cache saved successfully.")
        except IOError as e:
            print(f"[TRAP SERVICE] [ERROR] Could not write cache file: {e}")

    def _create_position_index(self) -> Dict[str, List[Tuple[int, int]]]:
        """
        Pre-processes all traps to create a map from a position's FEN
        to the traps and move indices that result in that position.
        """
        index_start_time = time.time()
        index = defaultdict(list)
        
        for trap in self.all_traps:
            if trap.id is None: continue # Skip traps without an ID (should not happen with DB)
            
            board = chess.Board()
            try:
                for i, move_san in enumerate(trap.moves):
                    move = board.parse_san(move_san)
                    board.push(move)
                    positional_fen = board.shredder_fen()
                    index[positional_fen].append((trap.id, i))
            except ValueError:
                # Optional: log invalid traps
                # print(f"[INDEX WARNING] Skipping trap ID {trap.id} due to invalid move.")
                continue
                
        index_end_time = time.time()
        print(f"[TRAP SERVICE] Indexing took {index_end_time - index_start_time:.2f} seconds.")
        return index

    def _get_matches_for_current_position(self, game_state: GameState) -> List[Tuple[ChessTrap, int]]:
        """
        Helper method to find all trap matches for the current board state using the index.
        Returns a list of (trap_object, move_index_in_trap).
        """
        if game_state.is_recording or not hasattr(self, 'position_index'):
            return []
            
        current_fen = game_state.board.shredder_fen()
        matching_entries = self.position_index.get(current_fen, [])
        
        results = []
        for trap_id, move_index in matching_entries:
            trap = self.id_to_trap_map.get(trap_id)
            if trap and trap.color == game_state.current_player:
                results.append((trap, move_index))
        return results

    def count_matching_traps(self, game_state: GameState) -> int:
        """Numără capcanele care se potrivesc cu poziția curentă, folosind indexul."""
        if not self.all_traps:
            return 0
            
        # La începutul jocului, FEN-ul este unic, deci putem folosi logica nouă
        if game_state.board.fullmove_number == 1 and game_state.board.turn == chess.WHITE:
             return sum(1 for trap in self.all_traps if trap.color == game_state.current_player)

        return len(self._get_matches_for_current_position(game_state))

    def get_aggregated_suggestions(self, game_state: GameState) -> List[MoveSuggestion]:
        """Obține sugestii agregate folosind noul index de poziții."""
        # Verifică dacă este rândul jucătorului uman să mute
        if game_state.board.turn != game_state.current_player:
            return []

        # Logică specială pentru poziția de start (fără mutări în istoric)
        if not game_state.move_history:
            move_groups = defaultdict(list)
            player_color_at_turn = game_state.board.turn
            
            for trap in self.all_traps:
                # Verificăm dacă trap-ul este pentru culoarea care e la mutare
                if trap.color == player_color_at_turn and trap.moves:
                    first_move = trap.moves[0]
                    move_groups[first_move].append(trap.moves)
            
            suggestions = []
            for move_san, continuations in move_groups.items():
                suggestions.append(MoveSuggestion(
                    suggested_move=move_san,
                    trap_count=len(continuations),
                    example_trap_line=continuations[0]
                ))
            
            suggestions.sort(key=lambda s: s.trap_count, reverse=True)
            return suggestions
            
        # Logica existentă pentru pozițiile de după prima mutare (folosind indexul)
        matches = self._get_matches_for_current_position(game_state)
        move_groups = defaultdict(list)
        
        for trap, move_index in matches:
            if len(trap.moves) > move_index + 1:
                next_move = trap.moves[move_index + 1]
                move_groups[next_move].append(trap.moves[move_index + 1:])
        
        suggestions = []
        for move_san, continuations in move_groups.items():
            suggestions.append(MoveSuggestion(
                suggested_move=move_san,
                trap_count=len(continuations),
                example_trap_line=continuations[0]
            ))
            
        suggestions.sort(key=lambda s: s.trap_count, reverse=True)
        return suggestions

    def get_most_common_response(self, game_state: GameState) -> Optional[str]:
        """Găsește cel mai comun răspuns al adversarului folosind indexul."""
        if game_state.board.turn == game_state.current_player:
            return None

        matches = self._get_matches_for_current_position(game_state)
        response_counts = defaultdict(int)
        
        for trap, move_index in matches:
            # Răspunsul adversarului este următoarea mutare din linie
            if len(trap.moves) > move_index + 1:
                opponent_response_san = trap.moves[move_index + 1]
                response_counts[opponent_response_san] += 1
        
        if not response_counts:
            return None
            
        return max(response_counts, key=response_counts.get)

class PGNImportService:
    """Service for importing traps from PGN files."""
    
    def __init__(self, repository: TrapRepository):
        self.repository = repository
    
    def import_from_file(self, file_path: str, max_moves: int = 25, checkmate_only: bool = False, progress_callback=None) -> Tuple[int, int]:
        """Import traps from a single PGN file."""
        print(f"[DEBUG PGN] Starting import from: {file_path}")
        
        try:
            white_traps, black_traps = self._parse_pgn_file(file_path, max_moves, checkmate_only)
            
            white_imported = self.repository.import_traps(white_traps)
            black_imported = self.repository.import_traps(black_traps)
            
            print(f"[DEBUG PGN] Import completed: {white_imported} white, {black_imported} black")
            return white_imported, black_imported
            
        except Exception as e:
            print(f"[DEBUG PGN ERROR] Import failed: {e}")
            import traceback
            traceback.print_exc()
            return 0, 0
    
    def import_from_folder(self, folder_path: str, max_moves: int = 25, checkmate_only: bool = False) -> Tuple[int, int]:
        """Import traps from all PGN files in a folder using parallel processing."""
        total_white = 0
        total_black = 0
        
        pgn_files = list(Path(folder_path).glob("*.pgn"))
        
        if not pgn_files:
            print(f"[DEBUG FOLDER] No PGN files found in {folder_path}")
            return 0, 0
        
        print(f"[DEBUG FOLDER] Found {len(pgn_files)} PGN files to process...")
        start_time = time.time()
        
        # Procesăm fișierele în paralel (dar nu prea multe deodată pentru a evita probleme de memorie)
        max_concurrent_files = min(4, cpu_count() // 2)  # Procesăm max 4 fișiere simultan
        
        with ProcessPoolExecutor(max_workers=max_concurrent_files) as executor:
            future_to_file = {
                executor.submit(self.import_from_file, str(pgn_file), max_moves, checkmate_only): pgn_file
                for pgn_file in pgn_files
            }
            
            for future in as_completed(future_to_file):
                pgn_file = future_to_file[future]
                try:
                    white_count, black_count = future.result()
                    total_white += white_count
                    total_black += black_count
                    print(f"[DEBUG FOLDER] Completed: {pgn_file.name} - {white_count} white, {black_count} black")
                except Exception as e:
                    print(f"[DEBUG FOLDER] Error processing {pgn_file.name}: {e}")
        
        elapsed = time.time() - start_time
        print(f"\n[DEBUG FOLDER] SUMMARY:")
        print(f"- Files processed: {len(pgn_files)}")
        print(f"- White traps found: {total_white}")
        print(f"- Black traps found: {total_black}")
        print(f"- Total time: {elapsed:.2f} seconds")
        
        return total_white, total_black
    
    def _parse_pgn_file(self, file_path: str, max_moves: int, checkmate_only: bool) -> Tuple[List[ChessTrap], List[ChessTrap]]:
        """Optimized parser that processes games in chunks using multiprocessing."""
        print(f"[DEBUG PGN PARSE] Opening file with MULTICORE method: {file_path}")
        
        # Citim toate jocurile o dată și le împărțim în chunk-uri
        games_data = []
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as pgn_file:
            game_strings = []
            current_game_lines = []
            
            for line in pgn_file:
                line = line.strip()
                if line.startswith('[') or line:  # Header sau mutări
                    current_game_lines.append(line)
                elif current_game_lines:  # Linie goală = sfârșitul unui joc
                    game_strings.append('\n'.join(current_game_lines))
                    current_game_lines = []
            
            # Nu uita ultimul joc dacă fișierul nu se termină cu linie goală
            if current_game_lines:
                game_strings.append('\n'.join(current_game_lines))
        
        print(f"[DEBUG PGN PARSE] Found {len(game_strings)} games to process")
        
        # Determinăm numărul optim de worker-i
        num_workers = min(cpu_count() - 1, 12)  # Lasă un core pentru sistem
        chunk_size = max(100, len(game_strings) // (num_workers * 4))  # Chunk-uri mai mici pentru load balancing mai bun
        
        # Împărțim jocurile în chunk-uri
        chunks = [game_strings[i:i + chunk_size] for i in range(0, len(game_strings), chunk_size)]
        
        white_traps = []
        black_traps = []
        
        print(f"[DEBUG PGN PARSE] Using {num_workers} workers with {len(chunks)} chunks")
        start_time = time.time()
        
        # Procesăm chunk-urile în paralel
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Submit all chunks for processing
            future_to_chunk = {
                executor.submit(self._process_games_chunk, chunk, max_moves, checkmate_only): i 
                for i, chunk in enumerate(chunks)
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_chunk):
                chunk_idx = future_to_chunk[future]
                try:
                    chunk_white, chunk_black = future.result()
                    white_traps.extend(chunk_white)
                    black_traps.extend(chunk_black)
                    
                    if chunk_idx % 10 == 0:  # Progress update
                        print(f"  ... processed chunk {chunk_idx + 1}/{len(chunks)}")
                except Exception as e:
                    print(f"[DEBUG PGN PARSE] Error processing chunk {chunk_idx}: {e}")
        
        elapsed = time.time() - start_time
        print(f"[DEBUG PGN PARSE] Processed {len(game_strings)} games in {elapsed:.2f} seconds")
        print(f"[DEBUG PGN PARSE] Found: {len(white_traps)} white traps, {len(black_traps)} black traps")
        
        return white_traps, black_traps


    @staticmethod
    def _process_games_chunk(game_strings: List[str], max_moves: int, checkmate_only: bool) -> Tuple[List[ChessTrap], List[ChessTrap]]:
        """Process a chunk of games. This runs in a separate process."""
        import chess.pgn  # Re-import în fiecare proces
        import io
        
        white_traps = []
        black_traps = []
        
        for game_string in game_strings:
            try:
                # Parsează jocul din string
                game = chess.pgn.read_game(io.StringIO(game_string))
                if game is None:
                    continue
                
                moves = list(game.mainline_moves())
                if not (4 <= len(moves) <= max_moves):
                    continue
                
                # Reconstruim tabla și notația SAN
                board = chess.Board()
                san_moves = []
                for move in moves:
                    san_moves.append(board.san(move))
                    board.push(move)
                
                # Verificare strictă pentru mat
                if not board.is_checkmate() or not san_moves[-1].endswith('#'):
                    continue
                
                # Determinăm culoarea câștigătoare
                num_moves = len(san_moves)
                trap_color = chess.WHITE if (num_moves % 2 != 0) else chess.BLACK
                
                trap_name = game.headers.get("Event", f"Imported Trap") + " (Checkmate)"
                trap = ChessTrap(name=trap_name, moves=san_moves, color=trap_color)
                
                if trap_color == chess.WHITE:
                    white_traps.append(trap)
                else:
                    black_traps.append(trap)
                    
            except Exception:
                # Skip problematic games silently
                continue
        
        return white_traps, black_traps

@dataclass
class OpeningInfo:
    """Informații despre o deschidere, citite din baza de date."""
    name: str
    eco_code: str
  
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
    """Bază de date eficientă pentru deschideri, folosind SQLite."""
    
    def __init__(self, db_path: str = "openings.db"):
        self.db_path = db_path
        if not os.path.exists(self.db_path):
            print(f"[ERROR] Opening database file not found: {self.db_path}")
            print("[ERROR] Please run build_opening_book.py first to create it.")
            self.conn = None
        else:
            try:
                # Deschidem în mod "immutable" (read-only) pentru siguranță și viteză
                db_uri = f"file:{self.db_path}?mode=ro"
                self.conn = sqlite3.connect(db_uri, uri=True, check_same_thread=False)
                cursor = self.conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM openings")
                count = cursor.fetchone()[0]
                print(f"[DEBUG INIT] Connection to opening book '{self.db_path}' successful. Found {count} entries.")
            except sqlite3.Error as e:
                print(f"[ERROR] Could not connect to opening book database: {e}")
                self.conn = None

    def get_opening_name(self, moves: List[str]) -> Optional[OpeningInfo]:
        """Găsește cea mai specifică deschidere pentru o listă de mutări printr-o interogare SQL."""
        if not self.conn or not moves:
            return None
            
        try:
            cursor = self.conn.cursor()
            for length in range(len(moves), 0, -1):
                current_sequence = moves[:length]
                moves_json = json.dumps(current_sequence)
                
                cursor.execute(
                    "SELECT name, eco_code FROM openings WHERE moves_json = ?",
                    (moves_json,)
                )
                result = cursor.fetchone()
                
                if result:
                    return OpeningInfo(name=result[0], eco_code=result[1])
            
            return None
        except sqlite3.Error as e:
            print(f"[DB ERROR] Error querying opening book: {e}")
            return None

    def get_opening_phase_info(self, moves: List[str]) -> Tuple[str, str]:
        """Returnează informații despre faza jocului pentru fiecare parte."""
        opening_info = self.get_opening_name(moves)
        
        if not opening_info:
            if not moves:
                return "Starting Position", "Starting Position"
            else:
                return "Out of book", "Out of book"

        base_text = f"{opening_info.name} ({opening_info.eco_code})"
        return base_text, base_text

    def get_total_openings(self) -> int:
        """Returns the total number of indexed opening lines."""
        if not self.conn:
            return 0
        # Putem returna lungimea dicționarului pe care l-am încărcat
        # sau, mai sigur, putem interoga direct DB-ul.
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(id) FROM openings")
            return cursor.fetchone()[0]
        except sqlite3.Error:
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
    
    def render_start_screen(self, surface: pygame.Surface, selected_color: chess.Color) -> Dict[str, pygame.Rect]:
        """Render the start screen."""
        surface.fill((30, 30, 30))
        
        button_rects = {}
        
        # Title
        title_text = "Chess Trap Trainer - Clean Architecture"
        title_surface = self.large_font.render(title_text, True, self.config.TEXT_COLOR)
        title_rect = title_surface.get_rect(center=(self.config.WIDTH // 2, 100))
        surface.blit(title_surface, title_rect)
        
        # Instructions
        instructions = "Choose your color:"
        inst_surface = self.font.render(instructions, True, self.config.TEXT_COLOR)
        inst_rect = inst_surface.get_rect(center=(self.config.WIDTH // 2, 200))
        surface.blit(inst_surface, inst_rect)
        
        # Color buttons
        button_width, button_height = 300, 50
        center_x = self.config.WIDTH // 2
        y_pos = 250
        
        white_rect = pygame.Rect(center_x - button_width // 2, y_pos, button_width, button_height)
        white_color = (100, 100, 100) if selected_color == chess.WHITE else (70, 70, 70)
        pygame.draw.rect(surface, white_color, white_rect, border_radius=5)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, white_rect, 2, border_radius=5)
        white_text = self.font.render("Play as White", True, self.config.TEXT_COLOR)
        surface.blit(white_text, white_text.get_rect(center=white_rect.center))
        button_rects["white"] = white_rect
        y_pos += 60

        black_rect = pygame.Rect(center_x - button_width // 2, y_pos, button_width, button_height)
        black_color = (100, 100, 100) if selected_color == chess.BLACK else (70, 70, 70)
        pygame.draw.rect(surface, black_color, black_rect, border_radius=5)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, black_rect, 2, border_radius=5)
        black_text = self.font.render("Play as Black", True, self.config.TEXT_COLOR)
        surface.blit(black_text, black_text.get_rect(center=black_rect.center))
        button_rects["black"] = black_rect
        y_pos += 80

        # Start button
        start_rect = pygame.Rect(center_x - 100, y_pos, 200, button_height)
        pygame.draw.rect(surface, (0, 120, 0), start_rect, border_radius=5)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, start_rect, 2, border_radius=5)
        start_text = self.font.render("Start Game", True, self.config.TEXT_COLOR)
        surface.blit(start_text, start_text.get_rect(center=start_rect.center))
        button_rects["start"] = start_rect
        y_pos += 80

        # --- BUTON NOU: DATABASE INFO ---
        info_rect = pygame.Rect(center_x - 125, y_pos, 250, 40)
        pygame.draw.rect(surface, (0, 80, 120), info_rect, border_radius=5) # Albastru închis
        pygame.draw.rect(surface, self.config.BORDER_COLOR, info_rect, 2, border_radius=5)
        info_text = self.small_font.render("Database Info", True, self.config.TEXT_COLOR)
        surface.blit(info_text, info_text.get_rect(center=info_rect.center))
        button_rects["info"] = info_rect

        return button_rects
    
    def render_game_screen(self, surface: pygame.Surface, state: GameState, 
                           suggestions: List[MoveSuggestion], total_matching_traps: int,
                           flipped: bool) -> Dict[str, pygame.Rect]:
        """Render the main game screen by orchestrating other render methods."""
        surface.fill((30, 30, 30))
        
        # Butoanele vor fi colectate din diversele panouri
        all_button_rects = {}
        
        # 1. Randează panoul de control
        control_rects = self.render_control_panel(surface, state)
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
        suggestions_button_rects = self.render_suggestions_panel(
            surface, 
            suggestions, 
            total_matching_traps
        )
        all_button_rects.update(suggestions_button_rects)
        
        # 5. Randează statusul
        self.render_status(surface, state)
        
        return all_button_rects
    
    def render_control_panel(self, surface: pygame.Surface, state: GameState) -> Dict[str, pygame.Rect]:
        """Render the control panel with buttons."""
        button_rects = {}
        
        # Panel background
        panel_rect = pygame.Rect(0, 0, self.config.BUTTONS_WIDTH, self.config.HEIGHT)
        pygame.draw.rect(surface, self.config.PANEL_COLOR, panel_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, panel_rect, 2)
        
        # Title
        title_surface = self.font.render("Controls:", True, self.config.TEXT_COLOR)
        surface.blit(title_surface, (10, 10))
        
        y_offset = 50
        button_height = 30
        button_width = 75
        spacing = 10
        
        # --- AICI ESTE MODIFICAREA ---
        # Am rearanjat lista pentru a se potrivi ordinii dorite:
        # 2 (<), 3 (>), 1 (|<), 4 (>|)
        buttons = [
            ("one_back", "<", 0, 0),        # Sus-stânga
            ("one_forward", ">", 1, 0),     # Sus-dreapta
            ("to_start", "|<", 0, 1),       # Jos-stânga
            ("to_end", ">|", 1, 1)          # Jos-dreapta
        ]
        
        for action, text, col, row in buttons:
            x = 20 + col * (button_width + spacing)
            y = y_offset + row * (button_height + spacing)
            
            rect = pygame.Rect(x, y, button_width, button_height)
            pygame.draw.rect(surface, self.config.BUTTON_COLOR, rect)
            pygame.draw.rect(surface, self.config.BORDER_COLOR, rect, 1)
            
            text_surface = self.small_font.render(text, True, self.config.TEXT_COLOR)
            text_rect = text_surface.get_rect(center=rect.center)
            surface.blit(text_surface, text_rect)
            
            button_rects[action] = rect
        
        # --- Restul metodei rămâne la fel ---
        y_offset += 85
        
        record_rect = pygame.Rect(20, y_offset, 160, 35)
        record_color = (120, 0, 0) if state.is_recording else (0, 120, 0)
        pygame.draw.rect(surface, record_color, record_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, record_rect, 1)
        
        record_text = "Stop Recording" if state.is_recording else "Record Trap"
        text_surface = self.small_font.render(record_text, True, self.config.TEXT_COLOR)
        text_rect = text_surface.get_rect(center=record_rect.center)
        surface.blit(text_surface, text_rect)
        button_rects["record"] = record_rect
        
        y_offset += 45
        
        import_buttons = [
            ("import_pgn", "Import PGN"),
            ("import_folder", "Import Folder"),
            ("main_menu", "Main Menu")
        ]
        
        for action, text in import_buttons:
            rect = pygame.Rect(20, y_offset, 160, 30)
            
            if action == "import_pgn": color = (0, 100, 0)
            elif action == "import_folder": color = (100, 0, 100)
            else: color = (100, 100, 0)
            
            pygame.draw.rect(surface, color, rect)
            pygame.draw.rect(surface, self.config.BORDER_COLOR, rect, 1)
            
            text_surface = self.small_font.render(text, True, self.config.TEXT_COLOR)
            text_rect = text_surface.get_rect(center=rect.center)
            surface.blit(text_surface, text_rect)
            
            button_rects[action] = rect
            y_offset += 35
        
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
    
    def render_suggestions_panel(self, surface: pygame.Surface, suggestions: List[MoveSuggestion], 
                           total_matching_traps: int) -> Dict[str, pygame.Rect]:
        """Render the suggestions panel with trap count and scrollable list."""
        button_rects = {}
        panel_rect = pygame.Rect(self.config.WIDTH - self.config.SUGGESTIONS_WIDTH, 0, self.config.SUGGESTIONS_WIDTH, self.config.HEIGHT)
        pygame.draw.rect(surface, self.config.PANEL_COLOR, panel_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, panel_rect, 2)
        
        y_offset = 20
        title_surface = self.font.render("Available Moves:", True, self.config.TEXT_COLOR)
        surface.blit(title_surface, (panel_rect.x + 10, y_offset))
        y_offset += 40
        
        # --- AICI ESTE MODIFICAREA ---
        traps_formatted = f"{total_matching_traps:_}".replace("_", " ")
        count_text = f"Matching traps: {traps_formatted}"
        count_surface = self.small_font.render(count_text, True, (255, 255, 0))
        surface.blit(count_surface, (panel_rect.x + 10, y_offset))
        y_offset += 30
        
        suggestions_area = pygame.Rect(panel_rect.x + 10, y_offset, panel_rect.width - 20, panel_rect.height - y_offset - 20)
        pygame.draw.rect(surface, (40, 40, 40), suggestions_area)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, suggestions_area, 1)
        
        if suggestions:
            suggestion_height = 40
            for i, suggestion in enumerate(suggestions):
                if i * suggestion_height > suggestions_area.height - suggestion_height:
                    break # Nu desena mai mult decât încape
                    
                suggestion_y = suggestions_area.y + i * suggestion_height
                suggestion_rect_rel = pygame.Rect(5, 5, suggestions_area.width - 10, suggestion_height - 10)
                suggestion_rect_abs = suggestion_rect_rel.move(suggestions_area.x, suggestion_y)
                
                pygame.draw.rect(surface, (60, 60, 60), suggestion_rect_abs)
                pygame.draw.rect(surface, self.config.BORDER_COLOR, suggestion_rect_abs, 1)
                
                # Formatăm și numărul de capcane pentru fiecare sugestie
                trap_count_formatted = f"{suggestion.trap_count:_}".replace("_", " ")
                suggestion_text = f"{i+1}. {suggestion.suggested_move} ({trap_count_formatted} traps)"
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

    def render_history_panel(self, surface: pygame.Surface, move_history: List[str]) -> pygame.Rect:
        """Renders the move history panel below the board with a copy button."""
        # Calculează poziția panoului mai jos, pentru a face loc numelui deschiderii
        panel_y = self.config.TOP_MARGIN + self.config.BOARD_SIZE + 80 # MODIFICAT de la +15
        panel_height = self.config.HEIGHT - panel_y - 20 # MODIFICAT pentru a fi dinamic
        
        # Asigură-te că panoul are o înălțime minimă și nu depășește ecranul
        if panel_height < 80: panel_height = 80
        if panel_y + panel_height > self.config.HEIGHT - 10:
            panel_height = self.config.HEIGHT - 10 - panel_y
            
        panel_rect = pygame.Rect(self.config.LEFT_MARGIN, panel_y, self.config.BOARD_SIZE, panel_height)
        
        # Fundalul panoului
        pygame.draw.rect(surface, (40, 40, 40), panel_rect, border_radius=5)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, panel_rect, 1, border_radius=5)
        
        # Construiește textul istoriei
        history_text = ""
        for i, move in enumerate(move_history):
            if i % 2 == 0:
                history_text += f"{i//2 + 1}. {move} "
            else:
                history_text += f"{move} "
                
        # Funcție ajutătoare pentru a desena text pe mai multe rânduri
        def draw_text_wrapped(surf, text, font, color, rect):
            words = text.split(' ')
            lines = []
            current_line = ""
            space_width = font.size(' ')[0]
            
            for word in words:
                # Verificăm lățimea liniei curente + noul cuvânt
                if font.size(current_line + word)[0] < rect.width - 20: # 20 = padding (10 stânga, 10 dreapta)
                    current_line += word + " "
                else:
                    lines.append(current_line)
                    current_line = word + " "
            lines.append(current_line)
            
            y_offset = rect.y + 10
            for line in lines:
                # Verificăm dacă mai este loc pe verticală
                if y_offset + font.get_height() > rect.y + rect.height - 40: # 40 = spațiu pentru buton
                    # Adăugăm "..." la ultima linie vizibilă
                    if lines.index(line) > 0:
                        last_visible_line = lines[lines.index(line)-1].strip() + "..."
                        # Ștergem ultima linie desenată pentru a o redesena cu "..."
                        y_offset -= font.get_height()
                        pygame.draw.rect(surf, (40,40,40), pygame.Rect(rect.x+1, y_offset, rect.width-2, font.get_height())) # Acoperă textul vechi
                        line_surf = font.render(last_visible_line, True, color)
                        surf.blit(line_surf, (rect.x + 10, y_offset))
                    break # Oprim desenarea
                    
                line_surf = font.render(line, True, color)
                surf.blit(line_surf, (rect.x + 10, y_offset))
                y_offset += font.get_height()

        draw_text_wrapped(surface, history_text.strip(), self.small_font, self.config.TEXT_COLOR, panel_rect)
        
        # Butonul de copiere
        copy_button_rect = pygame.Rect(panel_rect.right - 100, panel_rect.bottom - 35, 90, 25)
        pygame.draw.rect(surface, (80, 80, 150), copy_button_rect, border_radius=5)
        copy_text_surf = self.small_font.render("Copy", True, self.config.TEXT_COLOR)
        copy_text_rect = copy_text_surf.get_rect(center=copy_button_rect.center)
        surface.blit(copy_text_surf, copy_text_rect)
        
        return copy_button_rect

if QT_AVAILABLE:
    class QtImportWindow(QDialog):
        """A non-blocking Qt Dialog for PGN import settings."""
        
        def __init__(self, settings_service, on_start_import, on_clear_db, on_start_audit, parent=None):
            super().__init__(parent)
            
            self.setWindowTitle("Import & Database Management")
            
            # Stocăm serviciile și funcțiile callback
            self.settings_service = settings_service
            self.on_start_import = on_start_import
            self.on_clear_db = on_clear_db
            self.on_start_audit = on_start_audit # <--- LINIA NOUĂ DE AICI
            
            # Variabile interne
            self.full_filepath = ""
            self.settings = self.settings_service.load_settings()

            # Layout principal
            self.main_layout = QVBoxLayout(self)
            
            self._create_source_group()
            self._create_filters_group()
            self._create_database_group()
            self._create_actions_group()


        def start_audit(self):
            """Starts the audit process by calling the controller's callback."""
            try:
                max_moves = int(self.max_moves_edit.text())
                if max_moves < 4: raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Warning", "Please enter a valid number for max. semi-moves (>= 4) to use as a reference for the audit.")
                return

            # Salvăm setarea pentru consistență
            self.settings_service.update_setting("pgn_import_max_moves", max_moves)
            
            # Apelăm funcția de start din GameController
            self.on_start_audit(max_moves)
            
            self.accept() # Închide dialogul după ce a pornit auditul


        def _create_source_group(self):
            group_box = QGroupBox("Import Source")
            layout = QHBoxLayout()
            
            select_button = QPushButton("Select PGN File...")
            select_button.clicked.connect(self.select_file)
            
            self.file_label = QLabel("No file selected.")
            self.file_label.setStyleSheet("color: blue;")
            
            layout.addWidget(select_button)
            layout.addWidget(self.file_label, 1) # 1 = stretch factor
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)

        def _create_filters_group(self):
            group_box = QGroupBox("Import Filters")
            layout = QVBoxLayout()
            
            # Max moves
            h_layout = QHBoxLayout()
            h_layout.addWidget(QLabel("Max. semi-moves:"))
            self.max_moves_edit = QLineEdit(str(self.settings.get("pgn_import_max_moves", 25)))
            self.max_moves_edit.setFixedWidth(50)
            h_layout.addWidget(self.max_moves_edit)
            h_layout.addStretch()
            layout.addLayout(h_layout)
            
            # Checkmate only
            self.checkmate_only_checkbox = QCheckBox("Import only checkmating lines")
            self.checkmate_only_checkbox.setChecked(self.settings.get("checkmate_only", False))
            layout.addWidget(self.checkmate_only_checkbox)
            
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)

        def _create_database_group(self):
            group_box = QGroupBox("Database")
            layout = QHBoxLayout()
            
            clear_button = QPushButton("Clear All Traps")
            clear_button.setStyleSheet("background-color: #FF8A80;") # Roșu deschis
            clear_button.clicked.connect(self.on_clear_db)
            
            # --- Butonul NOU pentru AUDIT ---
            audit_button = QPushButton("Audit DB")
            audit_button.setStyleSheet("background-color: #C1A7E2; font-weight: bold;") # Mov
            audit_button.clicked.connect(self.start_audit) # Conectăm la o funcție nouă
            
            # Ordinea butoanelor în interfață
            layout.addWidget(audit_button)
            layout.addWidget(clear_button)
            layout.addStretch()
            
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)
            
        def _create_actions_group(self):
            # Linie de separare
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            self.main_layout.addWidget(line)

            button_layout = QHBoxLayout()
            button_layout.addStretch() # Aliniază butoanele la dreapta
            
            cancel_button = QPushButton("Cancel")
            cancel_button.clicked.connect(self.reject) # reject() închide dialogul
            
            self.start_button = QPushButton("START IMPORT")
            self.start_button.setStyleSheet("background-color: #B9F6CA; font-weight: bold;")
            self.start_button.clicked.connect(self.start_import)
            
            button_layout.addWidget(cancel_button)
            button_layout.addWidget(self.start_button)
            self.main_layout.addLayout(button_layout)

        def select_file(self):
            last_dir = self.settings.get("last_pgn_directory", "")
            filepath, _ = QFileDialog.getOpenFileName(self, "Select PGN File", last_dir, "PGN Files (*.pgn);;All Files (*)")
            
            if filepath:
                self.full_filepath = filepath
                display_path = os.path.basename(filepath)
                if len(filepath) > 40:
                    display_path = ".../" + display_path
                self.file_label.setText(display_path)
                self.settings_service.update_setting("last_pgn_directory", os.path.dirname(filepath))

        def start_import(self):
            if not self.full_filepath:
                QMessageBox.warning(self, "Warning", "Please select a PGN file first.")
                return

            try:
                max_moves = int(self.max_moves_edit.text())
                if max_moves < 4: raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Warning", "Please enter a valid number for max. semi-moves (>= 4).")
                return
            
            checkmate_only = self.checkmate_only_checkbox.isChecked()

            # Salvăm setările
            self.settings_service.update_setting("pgn_import_max_moves", max_moves)
            self.settings_service.update_setting("checkmate_only", checkmate_only)
            
            # Apelăm funcția de start din GameController
            self.on_start_import(self.full_filepath, max_moves, checkmate_only)
            
            self.accept() # accept() închide dialogul cu succes

    class QtInfoDialog(QDialog):
        """A simple dialog to display database statistics."""
        def __init__(self, stats: Dict[str, str], parent=None):
            super().__init__(parent)
            self.setWindowTitle("Database Statistics")
            self.setMinimumWidth(300)

            layout = QVBoxLayout(self)
            
            group_box = QGroupBox("Current Content")
            group_layout = QVBoxLayout()
            
            for key, value in stats.items():
                h_layout = QHBoxLayout()
                key_label = QLabel(f"<b>{key}:</b>") # Text aldin
                value_label = QLabel(value)
                value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                
                h_layout.addWidget(key_label)
                h_layout.addWidget(value_label)
                group_layout.addLayout(h_layout)

            group_box.setLayout(group_layout)
            layout.addWidget(group_box)
            
            # Buton de OK
            ok_button = QPushButton("OK")
            ok_button.clicked.connect(self.accept)
            layout.addWidget(ok_button, 0, Qt.AlignmentFlag.AlignCenter)

# Main Game Controller
class GameController:
    """Main controller that orchestrates the game."""
    
    def __init__(self):
        print("[DEBUG INIT] Initializing GameController...")
        
        self.qt_app = None
        if QT_AVAILABLE:
            self.qt_app = QApplication.instance() 
            if self.qt_app is None:
                print("[DEBUG INIT] Creating new QApplication instance.")
                self.qt_app = QApplication([])
        
        pygame.init()
        
        # --- MODIFICARE CHEIE ---
        # Creăm config-ul, APOI creăm componentele care depind de el
        self.config = UIConfig()
        
        print(f"[DEBUG INIT] UI Config: WIDTH={self.config.WIDTH}, HEIGHT={self.config.HEIGHT}")
        self.trap_repository = TrapRepository()
        self.trap_service = TrapService(self.trap_repository)
        self.pgn_service = PGNImportService(self.trap_repository)
        self.settings_service = SettingsService()
        self.opening_db = OpeningDatabase()  # <--- LINIA ADĂUGATĂ AICI
        
        self.screen = pygame.display.set_mode((self.config.WIDTH, self.config.HEIGHT))
        pygame.display.set_caption("Chess Trap Trainer - Clean Architecture")
        
        # Creăm loader-ul de piese cu noua dimensiune
        self.piece_loader = PieceImageLoader(self.config.SQUARE_SIZE)
        self.input_handler = InputHandler(self.config)
        # Creăm renderer-ul după ce avem toate componentele
        self.renderer = Renderer(self.config, self.piece_loader)
        
        initial_board = chess.Board()
        self.current_state = GameState(board=initial_board, current_player=chess.WHITE)
        self.text_input_visual = pygame_textinput.TextInputVisualizer()
        self.show_start_screen = True
        self.selected_color = chess.WHITE
        self.flipped = False
        self.move_history_forward = []
        self.current_suggestions = []
        self.highlighted_moves = []
        self.copy_button_rect = None
        
        print("[DEBUG INIT] GameController initialization complete!")
    
    
    def run(self) -> None:
        """Main game loop that also manages the Qt event loop."""
        print("[DEBUG MAIN] Starting main game loop...")
        
        clock = pygame.time.Clock()
        running = True
        
        self._update_suggestions()

        while running:
            if self.qt_app:
                self.qt_app.processEvents()
            
            events = pygame.event.get()
            
            if self.current_state.is_recording:
                if self.text_input_visual.update(events):
                    self._stop_recording()

            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                
                is_qt_window_active = False # Verificare dacă o fereastră Qt e activă
                if self.qt_app:
                    if self.qt_app.activeWindow() is not None:
                        is_qt_window_active = True
                
                if is_qt_window_active: continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.show_start_screen:
                        self._handle_start_screen_click(event.pos)
                    else:
                        self._handle_game_mousedown(event.pos)
                
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if not self.show_start_screen and self.current_state.dragging_piece:
                        self._handle_game_mouseup(event.pos)
                
                elif event.type == pygame.MOUSEMOTION:
                    if not self.show_start_screen and self.current_state.dragging_piece:
                        self.current_state.drag_pos = event.pos

                elif event.type == pygame.KEYDOWN:
                    if self.current_state.is_recording and event.key == pygame.K_RETURN:
                        self._stop_recording()

            # --- Randarea Pygame ---
            self.screen.fill((30, 30, 30))
            
            if self.show_start_screen:
                self.renderer.render_start_screen(self.screen, self.selected_color)
            else:
                self.renderer.render_control_panel(self.screen, self.current_state)
                self.renderer.render_board(self.screen, self.current_state, self.flipped)
                self.renderer.render_pieces(
                    self.screen, self.current_state.board, self.piece_loader,
                    self.current_state.selected_square, self.flipped,
                    self.current_state.dragging_piece, self.current_state.drag_pos
                )
                total_matching = self.trap_service.count_matching_traps(self.current_state)
                self.renderer.render_suggestions_panel(
                    self.screen, self.current_suggestions, total_matching
                )
                
                # --- BLOCUL MODIFICAT ESTE AICI ---
                # Obținem informațiile despre deschidere de la noul nostru serviciu
                white_info, black_info = self.opening_db.get_opening_phase_info(self.current_state.move_history)
                # Pasăm aceste informații către metoda de randare a statusului
                self.renderer.render_status(self.screen, self.current_state, white_info, black_info)
                # --- SFÂRȘITUL BLOCULUI MODIFICAT ---
                
                # Randăm panoul de istoric
                self.copy_button_rect = self.renderer.render_history_panel(
                    self.screen, 
                    self.current_state.move_history
                )

                if self.current_state.is_recording:
                     self.screen.blit(self.text_input_visual.surface, (self.config.LEFT_MARGIN, self.config.HEIGHT - 50))

            pygame.display.flip()
            clock.tick(60)
        
        print("[DEBUG MAIN] Main loop ended")
        pygame.quit()
    
    def _handle_start_screen_click(self, pos: Tuple[int, int]) -> None: # Am schimbat return type la None
        """Handle clicks on the start screen."""
        button_rects = self.renderer.render_start_screen(self.screen, self.selected_color)
        
        action = self.input_handler.handle_button_click(pos, button_rects)
        
        if action == "white":
            self.selected_color = chess.WHITE
        elif action == "black":
            self.selected_color = chess.BLACK
        elif action == "start":
            self._start_game(self.selected_color)
        elif action == "info": # --- CAZ NOU ---
            self._show_database_info()

    def _start_game(self, color: chess.Color) -> None:
        """Start a new game with the specified color."""
        print(f"[DEBUG START] Starting game with color: {chess.COLOR_NAMES[color]}")
        
        self.current_state = GameState(
            board=chess.Board(),
            current_player=color,
            is_recording=False,
            move_history=[],
            selected_square=None,
            dragging_piece=None,
            drag_pos=None
        )
        
        self.flipped = (color == chess.BLACK)
        self.show_start_screen = False
        self.move_history_forward = []
        
        print(f"[DEBUG START] Game started - Flipped: {self.flipped}")
        print(f"[DEBUG START] Initial board: {self.current_state.board.fen()}")
        
        # --- AICI ESTE CORECȚIA ESENȚIALĂ ---
        # Actualizăm sugestiile imediat și le stocăm în self.current_suggestions
        # pentru a fi disponibile la prima randare a ecranului de joc.
        self.current_suggestions = self.trap_service.get_aggregated_suggestions(self.current_state)
        print(f"[DEBUG START] Initial suggestions loaded. Found {len(self.current_suggestions)} move options.")

    def _clear_database(self):
        """Handles clearing the database using a non-blocking QMessageBox from PySide6."""
        if not QT_AVAILABLE:
            print("[DB] Cannot clear DB: Qt (PySide6) not available for confirmation dialog.")
            # Poate adăugăm un print simplu în consolă ca fallback
            # Răspuns = input("Ești sigur că vrei să ștergi totul? (da/nu): ")
            # if răspuns.lower() != 'da': return
            return
            
        # Creăm dialogul de confirmare folosind PySide6
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Confirm Deletion")
        msg_box.setText("Are you sure you want to permanently delete ALL traps from the database?")
        msg_box.setInformativeText("This action cannot be undone.")
        msg_box.setIcon(QMessageBox.Icon.Warning)
        
        # Adăugăm butoanele standard "Yes" și "No"
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        # Setăm "No" ca buton implicit (cel care este activat de tasta Enter)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        
        # Executăm dialogul și așteptăm răspunsul utilizatorului
        # Deoarece bucla Qt rulează în fundal, acest lucru nu va bloca Pygame complet
        response = msg_box.exec()
        
        # Verificăm ce buton a fost apăsat
        if response == QMessageBox.StandardButton.Yes:
            print("[DB] User confirmed deletion. Clearing all traps...")
            try:
                with sqlite3.connect(self.trap_repository.db_path) as conn:
                    conn.execute("DELETE FROM traps")
                
                # Re-inițializăm cache-ul din serviciu
                self.trap_service.all_traps = []
                
                # Afișăm un dialog de succes, tot cu PySide6
                QMessageBox.information(None, "Success", "The trap database has been successfully cleared.")
                self._update_suggestions() # Actualizăm UI-ul Pygame
            except Exception as e:
                QMessageBox.critical(None, "Error", f"Failed to clear the database: {e}")
                print(f"[DB ERROR] {e}")
        else:
            print("[DB] Deletion cancelled by user.")
    
    def _handle_game_mousedown(self, pos: Tuple[int, int]) -> None:
        """Handle mouse down events during main game."""
        
        # Verificăm întâi click-ul pe butonul de copiere
        if self.copy_button_rect and self.copy_button_rect.collidepoint(pos):
            history_text = ""
            for i, move in enumerate(self.current_state.move_history):
                if i % 2 == 0:
                    history_text += f"{i//2 + 1}. {move} "
                else:
                    history_text += f"{move} "
            
            pyperclip.copy(history_text.strip())
            print(f"[CLIPBOARD] Copiat: {history_text.strip()}")
            # Poți adăuga un scurt mesaj vizual aici, dacă dorești
            return # Ieșim devreme

        # Continuăm cu logica pentru celelalte butoane și tablă
        all_button_rects = {}
        control_rects = self.renderer.render_control_panel(pygame.Surface((self.config.BUTTONS_WIDTH, self.config.HEIGHT)), self.current_state)
        all_button_rects.update(control_rects)
        
        total_matching = self.trap_service.count_matching_traps(self.current_state)
        suggestion_rects = self.renderer.render_suggestions_panel(pygame.Surface((self.config.SUGGESTIONS_WIDTH, self.config.HEIGHT)), self.current_suggestions, total_matching)
        all_button_rects.update(suggestion_rects)
        
        action = self.input_handler.handle_button_click(pos, all_button_rects)
        
        if action:
            print(f"[DEBUG] Button action: {action}")
            self._handle_action(action)
        else:
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
            return
        
        if self.current_state.selected_square is None:
            # Select piece and start dragging
            piece = self.current_state.board.piece_at(square)
            
            if piece and piece.color == self.current_state.board.turn:
                print(f"[DEBUG] Starting drag of {piece} at {chess.square_name(square)}")
                self.current_state = GameState(
                    board=self.current_state.board,
                    current_player=self.current_state.current_player,
                    is_recording=self.current_state.is_recording,
                    move_history=self.current_state.move_history,
                    selected_square=square,
                    dragging_piece=piece,
                    drag_pos=pos
                )
        else:
            # Click while piece already selected - make move without drag
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
        """Resets all highlights and the active trap line."""
        self.current_state.highlighted_squares = None
        self.current_state.highlight_color = None
        self.current_state.active_trap_line = None

    def _handle_board_click(self, pos: Tuple[int, int]) -> None:
        """Handle clicks on the chess board (legacy method - kept for compatibility)."""
        # This method is now replaced by _handle_board_mousedown and _handle_board_mouseup
        # but kept here in case it's called from somewhere else
        self._handle_board_mousedown(pos)
    
    def _make_move(self, move: chess.Move) -> None:
        """Make a move and update the game state, including highlights and suggestions."""
        
        # Obținem culoarea care a făcut mutarea ÎNAINTE de a o aplica
        moving_color = self.current_state.board.turn
        move_san = self.current_state.board.san(move)

        # --- Actualizăm obiectul existent, nu creăm unul nou ---
        
        # 1. Actualizăm starea de bază a jocului
        self.current_state.board.push(move)
        self.current_state.move_history.append(move_san)
        self.current_state.selected_square = None
        self.current_state.dragging_piece = None
        self.current_state.drag_pos = None
        self.move_history_forward = []

        # 2. Resetăm highlight-urile înainte de a calcula altele noi
        self._clear_highlights()
        
        # --- AICI ESTE CORECȚIA CRUCIALĂ ---
        # Verificăm dacă culoarea care TOCMAI a mutat este a jucătorului uman
        if moving_color == self.current_state.current_player:
            # DA, a fost rândul nostru. Calculăm și setăm highlight-ul verde.
            print("[DEBUG] Player's move made. Calculating opponent's green highlight.")
            opponent_response_san = self.trap_service.get_most_common_response(self.current_state)
            
            if opponent_response_san:
                try:
                    opponent_move = self.current_state.board.parse_san(opponent_response_san)
                    self.current_state.highlighted_squares = (opponent_move.from_square, opponent_move.to_square)
                    self.current_state.highlight_color = self.config.HIGHLIGHT_GREEN
                    print(f"[DEBUG] Highlighting opponent's most common response: {opponent_response_san}")
                except ValueError:
                    print(f"[DEBUG] Could not parse opponent response '{opponent_response_san}'.")
            else:
                print("[DEBUG] No common opponent response found.")
                
            # Golește lista de sugestii, deoarece acum e rândul adversarului
            self.current_suggestions = []

        else:
            # NU, a fost rândul "adversarului". Acum trebuie să recalculăm sugestiile pentru noi.
            print("[DEBUG] Opponent's move made. Recalculating suggestions for player.")
            self._update_suggestions()
        
    def _update_suggestions(self) -> None:
        """
        Updates the list of suggestions. This should only be called when it's the
        player's turn to see new options.
        """
        if self.current_state.board.turn == self.current_state.current_player:
            self.current_suggestions = self.trap_service.get_aggregated_suggestions(self.current_state)
            print(f"[DEBUG] Updated suggestions for player. Found {len(self.current_suggestions)} move options.")
        else:
            # Dacă nu e rândul nostru, lista de sugestii trebuie să fie goală.
            self.current_suggestions = []
    
    def _update_game_state(self) -> None:
        """Update game state each frame."""
        # Handle text input for recording
        if self.current_state.is_recording:
            # Check for Enter key to stop recording
            keys = pygame.key.get_pressed()
            if keys[pygame.K_RETURN]:
                self._stop_recording()
    
    def _handle_action(self, action: str) -> None:
        """Handle various game actions."""
        if action == "to_start":
            self._go_to_start()
        elif action == "one_back":
            self._go_back_one()
        elif action == "one_forward":
            self._go_forward_one()
        elif action == "to_end":
            self._go_to_end()
        elif action == "record":
            if self.current_state.is_recording:
                self._stop_recording()
            else:
                self._start_recording()
        elif action == "import_pgn":
            self._import_pgn_file()
        elif action == "import_folder":
            self._import_pgn_folder()
        elif action == "main_menu":
            # AICI ESTE CORECȚIA: Asigură-te că apelează metoda corectă
            self._return_to_main_menu()
        elif action.startswith("suggestion_"):
            suggestion_index = int(action.split("_")[1])
            if 0 <= suggestion_index < len(self.current_suggestions):
                self._select_suggestion(self.current_suggestions[suggestion_index])
    
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
        """Go to the beginning of the game."""
        new_board = chess.Board()
        self.current_state = GameState(
            board=new_board,
            current_player=self.current_state.current_player,
            is_recording=self.current_state.is_recording,
            move_history=[],
            selected_square=None,
            dragging_piece=None,
            drag_pos=None
        )
        # Reconstruim istoricul forward din istoricul complet anterior
        full_history = self.current_state.move_history + self.move_history_forward
        self.move_history_forward = full_history
        
        self._clear_highlights() # ADAUGARE: Curăță highlight-urile
        self._update_suggestions()    

    def _go_back_one(self) -> None:
        """Go back one move."""
        if self.current_state.move_history:
            last_move = self.current_state.board.pop()
            self.move_history_forward.insert(0, self.current_state.move_history.pop())
            
            new_history = self.current_state.move_history
            new_board = self.current_state.board.copy() # Boardul este deja actualizat de .pop()
            
            self.current_state = GameState(
                board=new_board,
                current_player=self.current_state.current_player,
                is_recording=self.current_state.is_recording,
                move_history=new_history,
                selected_square=None,
                dragging_piece=None,
                drag_pos=None
            )
            
            self._clear_highlights() # ADAUGARE: Curăță highlight-urile
            self._update_suggestions()
    
    def _go_forward_one(self) -> None:
        """Go forward one move."""
        if self.move_history_forward:
            next_move_san = self.move_history_forward.pop(0)
            
            try:
                move = self.current_state.board.parse_san(next_move_san)
                new_board = self.current_state.board.copy()
                new_board.push(move)
                
                new_history = self.current_state.move_history + [next_move_san]
                self.current_state = GameState(
                    board=new_board,
                    current_player=self.current_state.current_player,
                    is_recording=self.current_state.is_recording,
                    move_history=new_history,
                    selected_square=None,
                    dragging_piece=None,
                    drag_pos=None
                )
                
                self._clear_highlights() # ADAUGARE: Curăță highlight-urile
                self._update_suggestions()
            except ValueError:
                print(f"[DEBUG] Invalid forward move: {next_move_san}")
                # Pune mutarea înapoi în listă dacă a eșuat
                self.move_history_forward.insert(0, next_move_san)
    
    def _go_to_end(self) -> None:
        """Go to the end of the game (the last known position)."""
        while self.move_history_forward:
            self._go_forward_one()
        
        # Asigură-te că și la final, orice highlight este curățat
        self._clear_highlights()
    
    def _start_recording(self) -> None:
        """Start recording a new trap."""
        self.current_state = GameState(
            board=self.current_state.board,
            current_player=self.current_state.current_player,
            is_recording=True,
            move_history=self.current_state.move_history,
            selected_square=self.current_state.selected_square,
            dragging_piece=self.current_state.dragging_piece,
            drag_pos=self.current_state.drag_pos
        )
        self.text_input_visual.value = ""  # Clear any previous input
    
    def _stop_recording(self) -> None:
        """Stop recording and save the trap."""
        if self.current_state.is_recording and self.current_state.move_history:
            trap_name = self.text_input_visual.value.strip()
            
            if not trap_name:
                trap_name = f"Custom Trap {len(self.current_state.move_history)} moves"
            
            # Create and save trap
            new_trap = ChessTrap(
                name=trap_name,
                moves=self.current_state.move_history.copy(),
                color=self.current_state.current_player
            )
            
            trap_id = self.trap_repository.save_trap(new_trap)
            print(f"[DEBUG] Saved new trap: {trap_name} (ID: {trap_id})")
            
            # Stop recording
            self.current_state = GameState(
                board=self.current_state.board,
                current_player=self.current_state.current_player,
                is_recording=False,
                move_history=self.current_state.move_history,
                selected_square=self.current_state.selected_square,
                dragging_piece=self.current_state.dragging_piece,
                drag_pos=self.current_state.drag_pos
            )
            
            # Refresh suggestions
            self._update_suggestions()
    
    def _import_pgn_file(self) -> None:
        """Opens the Qt Import Settings window."""
        if not QT_AVAILABLE:
            print("[IMPORT] Cannot import: PySide6 (Qt) is not available.")
            return

        # Funcția care va fi apelată de butonul "START IMPORT"
        def start_import_logic(filepath, max_moves, checkmate_only):
            print(f"[IMPORT] Starting import with settings...")
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_WAIT)
            
            white_count, black_count = self.pgn_service.import_from_file(filepath, max_moves, checkmate_only)
            
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
            
            QMessageBox.information(None, "Import Complete", f"Successfully imported:\n- {white_count} white traps\n- {black_count} black traps")
            
            # După import, forțăm reîmprospătarea datelor
            if os.path.exists(TrapService.CACHE_FILE_PATH):
                os.remove(TrapService.CACHE_FILE_PATH)
            self.trap_service = TrapService(self.trap_repository)
            self._update_suggestions()

        # Creăm și afișăm fereastra de dialog, pasând TOATE callback-urile necesare
        dialog = QtImportWindow(
            self.settings_service, 
            start_import_logic, 
            self._clear_database,
            self._run_database_audit  # Pasăm noua funcție de audit aici
        )
        dialog.exec()
        
    def _import_pgn_folder(self) -> None:
        """Opens a folder dialog using PySide6 to select a directory."""
        if not QT_AVAILABLE:
            print("[IMPORT] Cannot import folder: PySide6 (Qt) is not available.")
            return

        settings = self.settings_service.load_settings()
        last_directory = settings.get("last_pgn_directory", "")

        # Deschide dialogul de directoare Qt
        folder_path = QFileDialog.getExistingDirectory(
            None,
            "Select Folder with PGN Files",
            last_directory
        )

        if folder_path:
            print(f"[IMPORT] Folder selected: {folder_path}")
            QMessageBox.information(None, "Folder Selected", f"You selected:\n{folder_path}")
            
            self.settings_service.update_setting("last_pgn_directory", folder_path)
        else:
            print("[IMPORT] Folder selection cancelled.")
    
    def _return_to_main_menu(self) -> None:
        """Return to the main menu."""
        self.show_start_screen = True
        # Reset game state
        self.current_state = GameState(
            board=chess.Board(),
            current_player=chess.WHITE,
            # etc... celelalte câmpuri resetate
        )
        self.move_history_forward = []

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
        """Collects and displays database statistics in a Qt dialog."""
        if not QT_AVAILABLE:
            print("[INFO] Cannot show stats: PySide6 (Qt) is not available.")
            return

        # Colectează datele
        white_traps, black_traps = self.trap_repository.get_trap_counts_by_color()
        total_openings = self.opening_db.get_total_openings()
        
        # Formatează numerele pentru lizibilitate
        stats = {
            "White Traps": f"{white_traps:_}".replace("_", " "),
            "Black Traps": f"{black_traps:_}".replace("_", " "),
            "Total Traps": f"{white_traps + black_traps:_}".replace("_", " "),
            "Indexed Openings": f"{total_openings:_}".replace("_", " ")
        }
        
        # Creează și afișează dialogul
        dialog = QtInfoDialog(stats)
        dialog.exec()

def main():
    """Main entry point."""
    try:
        controller = GameController()
        controller.run()
    except Exception as e:
        print(f"[ERROR] Application error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Poți comenta auditul după ce ai văzut rezultatul
    # my_line_to_audit = ['e4', 'e5', 'Nf3', 'Nc6', 'Bc4', 'd6', 'Nc3']
    # audit_specific_line(my_line_to_audit)
    
    main()