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
from typing import List, Dict, Optional, Tuple, Protocol, Any
from pathlib import Path
from collections import defaultdict  # <--- ADAUGĂ ACEASTĂ LINIE AICI
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count


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
    """Represents a queen-hunting trap."""
    name: str
    moves: List[str]
    color: chess.Color  # Culoarea care câștigă regina
    capture_square: chess.Square
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


# Repository Layer

class TrapRepository:
    """Repository for managing chess traps in SQLite database."""
    
    def __init__(self, db_path: str = "chess_traps.db"):
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize the database with required tables for all trap types."""
        with sqlite3.connect(self.db_path) as conn:
            # Tabela pentru capcane de mat
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    moves TEXT NOT NULL,
                    color INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # NOU: Tabela pentru capcane de capturat regina
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queen_traps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    moves TEXT NOT NULL,
                    color INTEGER NOT NULL,
                    capture_square INTEGER NOT NULL
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

class QueenTrapRepository:
    """Repository for managing queen-hunting traps in SQLite database."""
    
    def __init__(self, db_path: str = "chess_traps.db"):
        self.db_path = db_path
        # Initializarea este deja făcută de TrapRepository, nu mai e nevoie aici

    def save_trap(self, trap: QueenTrap) -> int:
        """Save a queen trap to the database and return its ID."""
        # Verificăm dacă există deja un duplicat
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM queen_traps WHERE moves = ? AND color = ?",
                (json.dumps(trap.moves), int(trap.color))
            )
            if cursor.fetchone():
                print("[DB QUEEN] Duplicate queen trap found. Skipping save.")
                return -1  # Returnăm un ID invalid pentru a semnala duplicatul

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO queen_traps (name, moves, color, capture_square) VALUES (?, ?, ?, ?)",
                (trap.name, json.dumps(trap.moves), int(trap.color), trap.capture_square)
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_all_traps(self) -> List[QueenTrap]:
        """Get all queen traps from database."""
        traps = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT id, name, moves, color, capture_square FROM queen_traps")
                for row in cursor.fetchall():
                    trap_id, name, moves_json, color, capture_square = row
                    moves = json.loads(moves_json)
                    traps.append(QueenTrap(
                        id=trap_id, 
                        name=name, 
                        moves=moves, 
                        color=bool(color),
                        capture_square=int(capture_square)
                    ))
        except sqlite3.Error as e:
            print(f"[DB QUEEN ERROR] Could not read queen traps: {e}")
        return traps
        
    def delete_trap_by_id(self, trap_id: int) -> None:
        """Deletes a specific queen trap by its ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM queen_traps WHERE id = ?", (trap_id,))
            conn.commit()

    def get_total_trap_count(self) -> int:
        """Get total number of custom traps (queen traps table) in database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM queen_traps")
                return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0

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
                print(f"[INDEX WARNING] Skipping trap ID {trap.id} ('{trap.name}'). Invalid move: '{move_san}'. Error: {e}")
                continue
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
        """Obține sugestii agregate pentru mat, adăugând tipul capcanei."""
        if game_state.board.turn != game_state.current_player:
            return []

        # Logica pentru poziția de start
        if not game_state.move_history:
            move_groups = defaultdict(list)
            player_color_at_turn = game_state.board.turn
            
            for trap in self.all_traps:
                if trap.color == player_color_at_turn and trap.moves:
                    first_move = trap.moves[0]
                    move_groups[first_move].append(trap.moves)
            
            suggestions = [
                MoveSuggestion(
                    suggested_move=move_san,
                    trap_count=len(continuations),
                    example_trap_line=continuations[0],
                    trap_type='checkmate'  # Specificăm tipul
                ) for move_san, continuations in move_groups.items()
            ]
            suggestions.sort(key=lambda s: s.trap_count, reverse=True)
            return suggestions
            
        # Logica pentru pozițiile intermediare
        matches = self._get_matches_for_current_position(game_state)
        move_groups = defaultdict(list)
        
        for trap, move_index in matches:
            if len(trap.moves) > move_index + 1:
                next_move = trap.moves[move_index + 1]
                move_groups[next_move].append(trap.moves[move_index + 1:])
        
        suggestions = [
            MoveSuggestion(
                suggested_move=move_san,
                trap_count=len(continuations),
                example_trap_line=continuations[0],
                trap_type='checkmate'  # Specificăm tipul
            ) for move_san, continuations in move_groups.items()
        ]
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

    def add_new_trap_dynamically(self, trap: ChessTrap):
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
            print(f"[DYNAMIC INDEX] Failed to index new trap {trap.id}")
            return
        
        print(f"[TRAP SERVICE] Trap {trap.id} added dynamically to memory.")

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
    
    def force_reload(self):
        """Forțează reîncărcarea datelor din repository și reconstruirea indexului."""
        print("[QUEEN TRAP SERVICE] Forcing data reload...")
        self.all_traps = self.repository.get_all_traps()
        self.id_to_trap_map = {trap.id: trap for trap in self.all_traps}
        self.position_index = self._create_position_index()
        self._save_index_to_cache()
        print("[QUEEN TRAP SERVICE] Reload complete.")

    def get_aggregated_suggestions(self, game_state: GameState) -> List[MoveSuggestion]:
        """Obține sugestii agregate pentru capturarea reginei."""
        if game_state.board.turn != game_state.current_player:
            return []

        # Logica pentru poziția de start
        if not game_state.move_history:
            move_groups = defaultdict(list)
            player_color_at_turn = game_state.board.turn
            
            for trap in self.all_traps:
                if trap.color == player_color_at_turn and trap.moves:
                    first_move = trap.moves[0]
                    move_groups[first_move].append(trap.moves)
            
            suggestions = [
                MoveSuggestion(
                    suggested_move=move_san,
                    trap_count=len(continuations),
                    example_trap_line=continuations[0],
                    trap_type='queen_hunter' # Specificăm tipul
                ) for move_san, continuations in move_groups.items()
            ]
            suggestions.sort(key=lambda s: s.trap_count, reverse=True)
            return suggestions

        # Logica pentru pozițiile intermediare
        matches = self._get_matches_for_current_position(game_state)
        move_groups = defaultdict(list)
        
        for trap, move_index in matches:
            if len(trap.moves) > move_index + 1:
                next_move = trap.moves[move_index + 1]
                move_groups[next_move].append(trap.moves[move_index + 1:])
        
        suggestions = [
            MoveSuggestion(
                suggested_move=move_san,
                trap_count=len(continuations),
                example_trap_line=continuations[0],
                trap_type='queen_hunter' # Specificăm tipul
            ) for move_san, continuations in move_groups.items()
        ]
        suggestions.sort(key=lambda s: s.trap_count, reverse=True)
        return suggestions   

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

        # Butoane de acțiune principale
        action_buttons = [
            ("Record New Trap", "record", (0, 120, 0)),
            ("Import / Audit", "import_pgn", (0, 100, 150)),
            ("Database Info", "db_info", (0, 80, 120)),
            ("Reset Game", "main_menu", (150, 150, 0)) # Main Menu este acum Reset
        ]
        for text, action, color in action_buttons:
            rect = pygame.Rect(20, y_offset, self.config.BUTTONS_WIDTH - 40, 35)
            if action == "record" and state.is_recording:
                color, text = (180, 0, 0), "Confirm/Stop"
            pygame.draw.rect(surface, color, rect, border_radius=3)
            text_surf = self.small_font.render(text, True, self.config.TEXT_COLOR)
            surface.blit(text_surf, text_surf.get_rect(center=rect.center))
            button_rects[action] = rect
            y_offset += 45

        # Panoul de Istoric
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
        """A simple dialog to display database statistics."""
        def __init__(self, stats: Dict[str, str], parent=None):
            super().__init__(parent)
            self.setWindowTitle("Database Statistics")
            self.setMinimumWidth(350)

            layout = QVBoxLayout(self)
            
            group_box = QGroupBox("Current Content")
            group_layout = QVBoxLayout()
            
            for key, value in stats.items():
                if value == "":
                    line = QFrame()
                    line.setFrameShape(QFrame.Shape.HLine)
                    line.setFrameShadow(QFrame.Shadow.Sunken)
                    group_layout.addWidget(line)
                else:
                    h_layout = QHBoxLayout()
                    key_label = QLabel(f"{key}:")
                    if key.strip().startswith('-'):
                        key_label.setStyleSheet("padding-left: 20px;")

                    value_label = QLabel(f"<b>{value}</b>")
                    value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    
                    h_layout.addWidget(key_label)
                    h_layout.addWidget(value_label)
                    group_layout.addLayout(h_layout)

            group_box.setLayout(group_layout)
            layout.addWidget(group_box)
            
            ok_button = QPushButton("OK")
            ok_button.clicked.connect(self.accept)
            layout.addWidget(ok_button, 0, Qt.AlignmentFlag.AlignCenter)

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
        """A Qt Dialog to view and delete recorded queen traps."""
        def __init__(self, queen_trap_repo: QueenTrapRepository, on_trap_deleted, parent=None):
            super().__init__(parent)
            self.repo = queen_trap_repo
            self.on_trap_deleted = on_trap_deleted
            self.setWindowTitle("Queen Trap Manager")
            self.setMinimumSize(500, 400)
            self.main_layout = QVBoxLayout(self)
            scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True)
            self.container_widget = QWidget()
            self.list_layout = QVBoxLayout(self.container_widget)
            self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll_area.setWidget(self.container_widget)
            self.main_layout.addWidget(scroll_area)
            self.populate_list()

        def populate_list(self):
            while self.list_layout.count():
                child = self.list_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()
            all_traps = self.repo.get_all_traps()
            if not all_traps:
                self.list_layout.addWidget(QLabel("No queen traps recorded yet."))
                return
            for trap in all_traps:
                frame = QFrame(); frame.setFrameShape(QFrame.Shape.StyledPanel)
                layout = QHBoxLayout(frame)
                label = QLabel(f"<b>{trap.name}</b><br><small>{' '.join(trap.moves)}</small>")
                delete_button = QPushButton("Delete"); delete_button.setFixedSize(60, 25)
                delete_button.clicked.connect(lambda _, t_id=trap.id: self.delete_trap(t_id))
                layout.addWidget(label); layout.addStretch(); layout.addWidget(delete_button)
                self.list_layout.addWidget(frame)

        def delete_trap(self, trap_id: int):
            reply = QMessageBox.question(self, "Confirm", "Delete this trap?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.repo.delete_trap_by_id(trap_id)
                self.on_trap_deleted()
                self.populate_list()

    class QtImportWindow(QDialog):
        """A non-blocking Qt Dialog for PGN import settings."""
        def __init__(self, settings_service, on_start_import, on_clear_db, on_start_audit, on_manage_queen_traps, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Import & Database Management")
            self.settings_service = settings_service
            self.on_start_import = on_start_import
            self.on_clear_db = on_clear_db
            self.on_start_audit = on_start_audit
            self.on_manage_queen_traps = on_manage_queen_traps
            self.full_filepath = ""
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
            layout = QHBoxLayout()
            select_button = QPushButton("Select PGN File...")
            select_button.clicked.connect(self.select_file)
            self.file_label = QLabel("No file selected."); self.file_label.setStyleSheet("color: blue;")
            layout.addWidget(select_button); layout.addWidget(self.file_label, 1)
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)

        def _create_filters_group(self):
            group_box = QGroupBox("Import Filters"); layout = QVBoxLayout()
            h_layout = QHBoxLayout(); h_layout.addWidget(QLabel("Max. semi-moves:"))
            self.max_moves_edit = QLineEdit(str(self.settings.get("pgn_import_max_moves", 25)))
            self.max_moves_edit.setFixedWidth(50)
            h_layout.addWidget(self.max_moves_edit); h_layout.addStretch()
            layout.addLayout(h_layout)
            self.checkmate_only_checkbox = QCheckBox("Import only checkmating lines")
            self.checkmate_only_checkbox.setChecked(self.settings.get("checkmate_only", False))
            layout.addWidget(self.checkmate_only_checkbox)
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)

        def _create_database_group(self):
            group_box = QGroupBox("Database"); layout = QHBoxLayout()
            clear_button = QPushButton("Clear All Traps"); clear_button.setStyleSheet("background-color: #FF8A80;")
            clear_button.clicked.connect(self.on_clear_db)
            audit_button = QPushButton("Audit DB"); audit_button.setStyleSheet("background-color: #C1A7E2; font-weight: bold;")
            audit_button.clicked.connect(self.start_audit)
            manage_button = QPushButton("Manage Custom Traps"); manage_button.setStyleSheet("background-color: #82E0AA;")
            manage_button.clicked.connect(self.on_manage_queen_traps)
            layout.addWidget(audit_button); layout.addWidget(manage_button); layout.addStretch(); layout.addWidget(clear_button)
            group_box.setLayout(layout)
            self.main_layout.addWidget(group_box)
            
        def _create_actions_group(self):
            line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken)
            self.main_layout.addWidget(line)
            button_layout = QHBoxLayout(); button_layout.addStretch()
            cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject)
            self.start_button = QPushButton("START IMPORT"); self.start_button.setStyleSheet("background-color: #B9F6CA; font-weight: bold;")
            self.start_button.clicked.connect(self.start_import)
            button_layout.addWidget(cancel_button); button_layout.addWidget(self.start_button)
            self.main_layout.addLayout(button_layout)

        def select_file(self):
            last_dir = self.settings.get("last_pgn_directory", "")
            filepath, _ = QFileDialog.getOpenFileName(self, "Select PGN File", last_dir, "PGN Files (*.pgn)")
            if filepath:
                self.full_filepath = filepath
                self.file_label.setText("..." + filepath[-35:])
                self.settings_service.update_setting("last_pgn_directory", os.path.dirname(filepath))

        def start_import(self):
            if not self.full_filepath:
                QMessageBox.warning(self, "Warning", "Please select a PGN file first.")
                return
            try: max_moves = int(self.max_moves_edit.text())
            except ValueError: max_moves = 25
            checkmate_only = self.checkmate_only_checkbox.isChecked()
            self.settings_service.update_setting("pgn_import_max_moves", max_moves)
            self.settings_service.update_setting("checkmate_only", checkmate_only)
            self.on_start_import(self.full_filepath, max_moves, checkmate_only)
            self.accept()

# Main Game Controller
class GameController:
    """Main controller that orchestrates the game."""
    
    def __init__(self):
        print("[DEBUG INIT] Initializing GameController...")
        
        self.qt_app = QApplication.instance() 
        if self.qt_app is None:
            print("[DEBUG INIT] Creating new QApplication instance.")
            self.qt_app = QApplication([])
        
        pygame.init()
        
        self.config = UIConfig()
        
        self.trap_repository = TrapRepository()
        self.queen_trap_repository = QueenTrapRepository()
        
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
        
        # MODIFICAT: Nu mai avem ecran de start. Starea inițială este setată, dar goală.
        # Jocul propriu-zis va fi pornit în metoda `run`.
        self.current_state = GameState(board=chess.Board(), current_player=chess.WHITE)
        self.flipped = False
        self.move_history_forward = []
        self.current_suggestions = []
        
        # Am șters referințele la `show_start_screen` și `selected_color`
        
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
            total_matching = len(self.current_suggestions)
            
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
        total_matching = self.trap_service.count_matching_traps(self.current_state)
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
        
    def _update_suggestions(self) -> None:
        """
        Updates the list of suggestions by querying both trap services, combining
        the results, and prioritizing queen traps.
        """
        self.current_suggestions = []
        if self.current_state.board.turn == self.current_state.current_player:
            checkmate_suggs = self.trap_service.get_aggregated_suggestions(self.current_state)
            queen_suggs = self.queen_trap_service.get_aggregated_suggestions(self.current_state)
            
            all_suggs = checkmate_suggs + queen_suggs
            
            # --- NOUA LOGICĂ DE SORTARE ---
            # Sortăm în doi pași:
            # 1. Prioritizăm 'queen_hunter' (care va fi considerat 'mai mic' și va veni primul).
            # 2. Pentru același tip, sortăm descrescător după numărul de capcane.
            # Cheia de sortare este un tuplu: (prioritate_tip, -numar_capcane).
            # `s.trap_type == 'checkmate'` va evalua la 0 (False) pentru queen traps
            # și la 1 (True) pentru checkmate traps, sortându-le corect.
            # `-s.trap_count` sortează descrescător.
            
            all_suggs.sort(key=lambda s: (s.trap_type == 'checkmate', -s.trap_count))
            
            self.current_suggestions = all_suggs
            print(f"[DEBUG] Updated suggestions. Found {len(checkmate_suggs)} checkmate and {len(queen_suggs)} queen trap options. Queen traps prioritized.")
        else:
            # Dacă nu e rândul nostru, lista de sugestii trebuie să fie goală.
            self.current_suggestions = []

    def _manage_queen_traps(self):
        """Opens the Queen Trap management dialog."""
        if not QT_AVAILABLE:
            print("[MANAGE] Cannot manage traps: PySide6 (Qt) is not available.")
            return

        # Callback care va fi apelat din manager când o capcană este ștearsă
        def on_trap_deleted_callback():
            print("[CONTROLLER] A queen trap was deleted. Forcing service reload.")
            self.queen_trap_service.force_reload()
            self._update_suggestions()

        dialog = QtQueenTrapManager(self.queen_trap_repository, on_trap_deleted_callback)
        dialog.exec()
    
    def _update_game_state(self) -> None:
        """Update game state each frame."""
        # Handle text input for recording
        if self.current_state.is_recording:
            # Check for Enter key to stop recording
            keys = pygame.key.get_pressed()
            if keys[pygame.K_RETURN]:
                self._stop_recording()
    
    def _handle_action(self, action: str) -> None:
        """Handle various game actions with context-aware recording."""
        
        allowed_in_recording = {"record", "main_menu", "one_back", "one_forward"}
        if self.current_state.is_recording and action not in allowed_in_recording:
            print(f"[REC] Action '{action}' disabled while recording.")
            return

        # --- Acțiuni Noi ---
        if action == "play_as_white":
            self._start_game(chess.WHITE)
            return
        if action == "play_as_black":
            self._start_game(chess.BLACK)
            return
        if action == "db_info":
            self._show_database_info()
            return
        # ------------------
        
        if action == "to_start": self._go_to_start()
        elif action == "one_back": self._go_back_one()
        elif action == "one_forward": self._go_forward_one()
        elif action == "to_end": self._go_to_end()
        elif action == "record":
            if not self.current_state.is_recording:
                self._start_game(self.current_state.current_player, is_recording=True) # Pornim un joc nou în mod record
            else:
                self._handle_stop_recording_request(self.current_state.recording_history)
        elif action == "import_pgn": self._import_pgn_file()
        elif action == "main_menu": 
            self._start_game(self.current_state.current_player) # Main Menu acum resetează jocul
        elif action.startswith("suggestion_"):
            if not self.current_state.is_recording:
                idx = int(action.split("_")[1])
                if 0 <= idx < len(self.current_suggestions):
                    self._select_suggestion(self.current_suggestions[idx])

    
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
        """Go back one move in either normal play or recording mode."""
        # --- Logica pentru modul de înregistrare ---
        if self.current_state.is_recording:
            if self.current_state.recording_history:
                self.current_state.board.pop()
                # Mutăm ultima mutare din istoricul de înregistrare în cel de "forward"
                last_move_san = self.current_state.recording_history.pop()
                self.move_history_forward.insert(0, last_move_san)
                # Actualizăm și istoricul de afișare
                self.current_state.move_history.pop()
                print(f"[REC] Went back. Last move was: {last_move_san}")
            return

        # --- Logica pentru modul de joc normal (neschimbată) ---
        if self.current_state.move_history:
            self.current_state.board.pop()
            self.move_history_forward.insert(0, self.current_state.move_history.pop())
            self._clear_highlights()
            self._update_suggestions()
    
    def _go_forward_one(self) -> None:
        """Go forward one move in either normal play or recording mode."""
        # --- Logica pentru modul de înregistrare ---
        if self.current_state.is_recording:
            if self.move_history_forward:
                next_move_san = self.move_history_forward.pop(0)
                try:
                    move = self.current_state.board.parse_san(next_move_san)
                    self.current_state.board.push(move)
                    # Adăugăm mutarea înapoi în ambele istorice
                    self.current_state.recording_history.append(next_move_san)
                    self.current_state.move_history.append(next_move_san)
                    print(f"[REC] Went forward. Move: {next_move_san}")
                except ValueError:
                    self.move_history_forward.insert(0, next_move_san)
            return

        # --- Logica pentru modul de joc normal (neschimbată) ---
        if self.move_history_forward:
            next_move_san = self.move_history_forward.pop(0)
            try:
                move = self.current_state.board.parse_san(next_move_san)
                self._make_move(move) # Re-folosim _make_move pentru a re-calcula totul corect
            except ValueError:
                self.move_history_forward.insert(0, next_move_san)
    
    def _go_to_end(self) -> None:
        """Go to the end of the game (the last known position)."""
        while self.move_history_forward:
            self._go_forward_one()
        
        # Asigură-te că și la final, orice highlight este curățat
        self._clear_highlights()
    
    def _start_recording(self) -> None:
        """Prepares the state for a new recording from scratch."""
        print("[REC] New recording session started. Board is reset.")
        self.current_state.is_recording = True
        self.current_state.board.reset()
        self.current_state.recording_history = []
        self.current_state.move_history = []
        self.move_history_forward = []
        self.current_suggestions = []
        self._clear_highlights()

    def _handle_stop_recording_request(self, moves_to_analyze: List[str]):
        """
        Handles a request to save a line, using the provided move list.
        """
        if not moves_to_analyze:
            print("[REC] No moves to save.")
            self.current_state.is_recording = False
            return

        detected_type, winning_color = self._analyze_recorded_line(moves_to_analyze)

        # Determinăm ce decizie să luăm (prin Qt sau consolă)
        decision = None
        if QT_AVAILABLE:
            decision = QtSaveConfirmDialog.get_decision(detected_type, moves_to_analyze)
        else:
            # --- LOGICA DE FALLBACK PENTRU CONSOLĂ (COMPLETATĂ) ---
            print("\n" + "="*30)
            print(f"  POTENTIAL TRAP DETECTED")
            print(f"  Type: {detected_type}")
            print(f"  Moves: {' '.join(moves_to_analyze)}")
            print("="*30)
            
            while decision is None:
                choice = input("Action: [S]ave, [C]ancel, or co[N]tinue recording? ").lower()
                if choice == 's':
                    decision = QtSaveConfirmDialog.SAVE
                elif choice == 'c':
                    decision = QtSaveConfirmDialog.CANCEL
                elif choice == 'n':
                    decision = QtSaveConfirmDialog.CONTINUE
                else:
                    print("Invalid choice. Please enter 's', 'c', or 'n'.")

        # Acum acționăm pe baza deciziei luate
        if decision == QtSaveConfirmDialog.SAVE:
            print("[REC] User chose to save the trap.")
            self._save_trap_logic(detected_type, winning_color, moves_to_analyze)
            # După salvare, cel mai sigur e să ne întoarcem la meniu
            self._return_to_main_menu()

        elif decision == QtSaveConfirmDialog.CANCEL:
            print("[REC] User cancelled the save/recording.")
            # Dacă eram în modul de înregistrare, îl oprim și mergem la meniu
            if self.current_state.is_recording:
                self._return_to_main_menu()
            # Dacă doar am anulat salvarea unui joc normal, nu facem nimic, rămânem în joc
                
        elif decision == QtSaveConfirmDialog.CONTINUE:
            # Această opțiune are sens doar dacă eram deja în modul de înregistrare
            if self.current_state.is_recording:
                print("[REC] Continuing recording...")
            else:
                # Dacă am încercat să salvăm un joc normal, "continue" nu face nimic
                print("[REC] Save action cancelled.")
        

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

        # Toate capcanele custom, indiferent de tip, merg în sistemul 'queen_traps'
        # Numele va reflecta tipul real
        trap_name = f"{detected_type.replace(' ', '')} ({moves[0]}...)"
        
        # Pentru 'capture_square', folosim o valoare generică dacă e mat
        capture_square = 0 
        if detected_type in ["Direct Queen Capture", "Royal Fork"]:
            final_board = chess.Board()
            for move_san in moves: 
                final_board.push(final_board.parse_san(move_san.replace('#','').replace('+','')))
            opponent_color = not winning_color
            queen_square_set = final_board.pieces(chess.QUEEN, opponent_color)
            if queen_square_set:
                capture_square = queen_square_set.pop()

        # Creăm obiectul și îl salvăm în repository-ul rapid
        new_custom_trap = QueenTrap(
            name=trap_name, 
            moves=moves, 
            color=winning_color, 
            capture_square=capture_square
        )
        
        trap_id = self.queen_trap_repository.save_trap(new_custom_trap)
        
        if trap_id != -1:
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
        # --- AICI ESTE CORECȚIA ---
        dialog = QtImportWindow(
            self.settings_service, 
            start_import_logic, 
            self._clear_database,
            self._run_database_audit,
            self._manage_queen_traps  # Am adăugat argumentul lipsă
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
            print("[INFO] Cannot show stats: PySide6 (Qt) is not available.")
            # Fallback pentru consolă
            pgn_traps = self.trap_repository.get_total_trap_count()
            custom_traps = self.queen_trap_repository.get_total_trap_count()
            print("\n--- DATABASE STATS ---")
            print(f"  PGN Checkmate Traps: {pgn_traps}")
            print(f"  Manually Recorded Traps: {custom_traps}")
            print(f"  Total Traps: {pgn_traps + custom_traps}")
            print("----------------------\n")
            return

        # Colectează datele folosind repository-urile
        pgn_checkmates = self.trap_repository.get_total_trap_count()
        manually_recorded = self.queen_trap_repository.get_total_trap_count()
        
        # Numărăm specific capcanele de tip "Queen Hunt" din cele custom
        all_custom_traps = self.queen_trap_repository.get_all_traps()
        queen_hunt_count = sum(1 for trap in all_custom_traps if 'Queen' in trap.name or 'Fork' in trap.name)
        recorded_mates_count = manually_recorded - queen_hunt_count
        
        total_traps = pgn_checkmates + manually_recorded
        
        # Formatează numerele pentru lizibilitate
        stats = {
            "PGN Checkmate Library": f"{pgn_checkmates:_}".replace("_", " "),
            "-----------------------------": "", # Separator vizual
            "Manually Recorded Traps": f"{manually_recorded:_}".replace("_", " "),
            "   - Queen Hunts / Forks": f"{queen_hunt_count:_}".replace("_", " "),
            "   - Checkmates": f"{recorded_mates_count:_}".replace("_", " "),
            "=============================": "", # Separator vizual
            "Total Unique Traps": f"{total_traps:_}".replace("_", " "),
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