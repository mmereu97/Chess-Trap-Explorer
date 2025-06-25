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


# Configuration and Data Classes
@dataclass
class UIConfig:
    """UI configuration constants for 1080p resolution with history panel."""
    # --- Rezoluția totală ---
    WIDTH: int = 1920
    HEIGHT: int = 1080
    
    # --- Dimensiuni Panouri ---
    BUTTONS_WIDTH: int = 280
    SUGGESTIONS_WIDTH: int = 500
    
    # --- Dimensiuni Tablă și Panou Istoric ---
    # Lăsăm un spațiu total de 950px pe verticală pentru tablă + istoric
    BOARD_AREA_HEIGHT: int = 950
    # Tabla va ocupa o parte din acest spațiu
    BOARD_SIZE: int = 768
    SQUARE_SIZE: int = BOARD_SIZE // 8  # 96px per pătrățel
    
    # --- Margini ---
    TOP_MARGIN: int = 50 # O margine superioară fixă
    LEFT_MARGIN: int = BUTTONS_WIDTH + 60
    
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
            return cursor.lastrowid
    
    def get_all_traps(self) -> List[ChessTrap]:
        """Get all traps from database."""
        traps = []
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT id, name, moves, color FROM traps")
            
            for row in cursor.fetchall():
                trap_id, name, moves_json, color = row
                moves = json.loads(moves_json)
                traps.append(ChessTrap(
                    id=trap_id,
                    name=name,
                    moves=moves,
                    color=bool(color)
                ))
        
        return traps
    
    def get_total_trap_count(self) -> int:
        """Get total number of traps in database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM traps")
            return cursor.fetchone()[0]
    
    def import_traps(self, traps: List[ChessTrap]) -> int:
        """Highly optimized batch import with minimal database queries."""
        if not traps:
            return 0
            
        imported_count = 0
        start_time = time.time()
        
        with sqlite3.connect(self.db_path) as conn:
            # Optimizări critice pentru viteză
            conn.execute("PRAGMA journal_mode = MEMORY")
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
            conn.execute("PRAGMA temp_store = MEMORY")
            
            # 1. Citim TOATE trap-urile existente O SINGURĂ DATĂ
            print(f"[DEBUG DB] Checking for duplicates among {len(traps)} traps...")
            cursor = conn.execute("SELECT moves, color FROM traps")
            existing_signatures = set()
            for row in cursor:
                existing_signatures.add((row[0], row[1]))
            print(f"[DEBUG DB] Found {len(existing_signatures)} existing traps in database")
            
            # 2. Pregătim datele pentru batch insert, filtrând duplicatele
            batch_data = []
            skipped = 0
            
            for trap in traps:
                moves_json = json.dumps(trap.moves)
                signature = (moves_json, int(trap.color))
                
                if signature not in existing_signatures:
                    batch_data.append((trap.name, moves_json, int(trap.color)))
                    existing_signatures.add(signature)  # Adaugă în set pentru a evita duplicate în același batch
                    imported_count += 1
                else:
                    skipped += 1
            
            # 3. Facem UN SINGUR batch insert pentru TOATE trap-urile noi
            if batch_data:
                print(f"[DEBUG DB] Inserting {len(batch_data)} new traps in a single batch...")
                conn.executemany(
                    "INSERT INTO traps (name, moves, color) VALUES (?, ?, ?)",
                    batch_data
                )
                conn.commit()
            
            # Reactivăm setările normale
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        
        elapsed = time.time() - start_time
        print(f"[DEBUG DB] Import complete in {elapsed:.2f} seconds: {imported_count} added, {skipped} duplicates skipped")
        
        return imported_count

# Service Layer
class TrapService:
    """Service for managing trap logic and suggestions."""
    
    def __init__(self, repository: TrapRepository):
        self.repository = repository
        # Încărcăm toate capcanele o singură dată la inițializare pentru performanță
        self.all_traps = self.repository.get_all_traps()
    
    def _get_matching_traps(self, game_state: GameState) -> List[ChessTrap]:
        if game_state.is_recording: return []
        target_color = game_state.current_player
        matching_traps = []
        history_len = len(game_state.move_history)
        for trap in self.all_traps:
            if (trap.color == target_color and
                len(trap.moves) > history_len and
                trap.moves[:history_len] == game_state.move_history):
                matching_traps.append(trap)
        return matching_traps

    def count_matching_traps(self, game_state: GameState) -> int:
        """Numără toate capcanele care se potrivesc cu poziția curentă."""
        # La începutul jocului (fără mutări), numără toate capcanele pentru jucătorul curent
        if not game_state.move_history:
            return sum(1 for trap in self.all_traps if trap.color == game_state.current_player)
        return len(self._get_matching_traps(game_state))

    def get_aggregated_suggestions(self, game_state: GameState) -> List[MoveSuggestion]:
        if game_state.board.turn != game_state.current_player: return []
        
        matching_traps = self._get_matching_traps(game_state)
        history_len = len(game_state.move_history)
        move_groups = defaultdict(list)
        
        # Următoarea mutare trebuie să fie a jucătorului
        if (history_len % 2 == 0 and game_state.current_player == chess.WHITE) or \
           (history_len % 2 != 0 and game_state.current_player == chess.BLACK):
            for trap in matching_traps:
                next_move = trap.moves[history_len]
                move_groups[next_move].append(trap)
                
        suggestions = []
        for move_san, traps in move_groups.items():
            suggestions.append(MoveSuggestion(
                suggested_move=move_san,
                trap_count=len(traps),
                example_trap_line=traps[0].moves[history_len:]
            ))
        suggestions.sort(key=lambda s: s.trap_count, reverse=True)
        return suggestions

    def get_most_common_response(self, game_state: GameState) -> Optional[str]:
        if game_state.board.turn == game_state.current_player: return None

        matching_traps = self._get_matching_traps(game_state)
        history_len = len(game_state.move_history)
        response_counts = defaultdict(int)
        
        # Următoarea mutare trebuie să fie a adversarului
        if (history_len % 2 != 0 and game_state.current_player == chess.WHITE) or \
           (history_len % 2 == 0 and game_state.current_player == chess.BLACK):
            for trap in matching_traps:
                if len(trap.moves) > history_len:
                    opponent_response_san = trap.moves[history_len]
                    response_counts[opponent_response_san] += 1
        
        if not response_counts: return None
        return max(response_counts, key=response_counts.get)

class PGNImportService:
    """Service for importing traps from PGN files."""
    
    def __init__(self, repository: TrapRepository):
        self.repository = repository
    
    def import_from_file(self, file_path: str, max_moves: int = 25, checkmate_only: bool = False, progress_callback=None) -> Tuple[int, int]:
        """Import traps from a single PGN file with optimized batch processing."""
        print(f"[DEBUG PGN] Starting import from: {file_path}")
        
        try:
            white_traps, black_traps = self._parse_pgn_file(file_path, max_moves, checkmate_only)
            
            # Combinăm toate trap-urile pentru un singur batch import
            all_traps = white_traps + black_traps
            
            print(f"[DEBUG PGN] Sending {len(all_traps)} traps to database...")
            imported_total = self.repository.import_traps(all_traps)
            
            # Calculăm aproximativ câte au fost albe/negre din cele importate
            white_ratio = len(white_traps) / len(all_traps) if all_traps else 0
            white_imported = int(imported_total * white_ratio)
            black_imported = imported_total - white_imported
            
            print(f"[DEBUG PGN] Import completed: ~{white_imported} white, ~{black_imported} black")
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
        
        # White button
        white_rect = pygame.Rect(center_x - button_width // 2, 250, button_width, button_height)
        white_color = (100, 100, 100) if selected_color == chess.WHITE else (70, 70, 70)
        pygame.draw.rect(surface, white_color, white_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, white_rect, 2)
        
        white_text = self.font.render("Play as White", True, self.config.TEXT_COLOR)
        white_text_rect = white_text.get_rect(center=white_rect.center)
        surface.blit(white_text, white_text_rect)
        button_rects["white"] = white_rect
        
        # Black button
        black_rect = pygame.Rect(center_x - button_width // 2, 310, button_width, button_height)
        black_color = (100, 100, 100) if selected_color == chess.BLACK else (70, 70, 70)
        pygame.draw.rect(surface, black_color, black_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, black_rect, 2)
        
        black_text = self.font.render("Play as Black", True, self.config.TEXT_COLOR)
        black_text_rect = black_text.get_rect(center=black_rect.center)
        surface.blit(black_text, black_text_rect)
        button_rects["black"] = black_rect
        
        # Start button
        start_rect = pygame.Rect(center_x - 100, 400, 200, button_height)
        pygame.draw.rect(surface, (0, 120, 0), start_rect)
        pygame.draw.rect(surface, self.config.BORDER_COLOR, start_rect, 2)
        
        start_text = self.font.render("Start Game", True, self.config.TEXT_COLOR)
        start_text_rect = start_text.get_rect(center=start_rect.center)
        surface.blit(start_text, start_text_rect)
        button_rects["start"] = start_rect
        
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
        
        # NOU: Afișează numărul de capcane care se potrivesc
        count_text = f"Matching traps: {total_matching_traps}"
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
                
                # NOU: Afișează sugestia în format "1. Nf3 (150 traps)"
                suggestion_text = f"{i+1}. {suggestion.suggested_move} ({suggestion.trap_count} traps)"
                text_surface = self.small_font.render(suggestion_text, True, self.config.TEXT_COLOR)
                surface.blit(text_surface, (suggestion_rect_abs.x + 10, suggestion_rect_abs.y + 10))
                
                button_rects[f"suggestion_{i}"] = suggestion_rect_abs
        else:
            no_suggestions = self.small_font.render("No available traps for this line", True, (150, 150, 150))
            text_rect = no_suggestions.get_rect(center=suggestions_area.center)
            surface.blit(no_suggestions, text_rect)
            
        return button_rects
    
    def render_status(self, surface: pygame.Surface, state: GameState) -> None:
        """Render game status information above the board."""
        # Mutăm statusul deasupra tablei
        status_y = self.config.TOP_MARGIN - 40
        
        turn_text = "Your turn to move" if state.board.turn == state.current_player else "Opponent's turn"
        turn_surface = self.font.render(turn_text, True, self.config.TEXT_COLOR)
        
        status_rect = pygame.Rect(self.config.LEFT_MARGIN, status_y, self.config.BOARD_SIZE, 35)
        
        text_rect = turn_surface.get_rect(center=status_rect.center)
        surface.blit(turn_surface, text_rect)
        
        if state.is_recording:
            record_text = "RECORDING - Type trap name and press Enter"
            record_surface = self.small_font.render(record_text, True, (255, 100, 100))
            surface.blit(record_surface, (self.config.LEFT_MARGIN, status_y - 25))

    def render_history_panel(self, surface: pygame.Surface, move_history: List[str]) -> pygame.Rect:
        """Renders the move history panel below the board with a copy button."""
        # Calculează poziția panoului sub tablă
        panel_y = self.config.TOP_MARGIN + self.config.BOARD_SIZE + 15
        panel_height = self.config.HEIGHT - panel_y - 20
        # Asigură-te că panoul are o înălțime minimă
        if panel_height < 60:
            panel_height = 60
            panel_y = self.config.HEIGHT - 20 - panel_height
            
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
        
        def __init__(self, settings_service, on_start_import, on_clear_db, parent=None):
            super().__init__(parent)
            
            self.setWindowTitle("Import & Database Management")
            
            # Stocăm serviciile și funcțiile callback
            self.settings_service = settings_service
            self.on_start_import = on_start_import
            self.on_clear_db = on_clear_db
            
            # Variabile interne
            self.full_filepath = ""
            self.settings = self.settings_service.load_settings()

            # Layout principal
            self.main_layout = QVBoxLayout(self)
            
            self._create_source_group()
            self._create_filters_group()
            self._create_database_group()
            self._create_actions_group()

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
            clear_button.setStyleSheet("background-color: #FF8A80;")
            clear_button.clicked.connect(self.on_clear_db)
            
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
        self.copy_button_rect = None # ADAUGĂ ACEASTĂ LINIE
    
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
                self.renderer.render_status(self.screen, self.current_state)
                
                # APEL NOU: Randăm panoul de istoric
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
    
    def _handle_start_screen_click(self, pos: Tuple[int, int]) -> bool:
        """Handle clicks on the start screen."""
        # Render to get button positions
        button_rects = self.renderer.render_start_screen(self.screen, self.selected_color)
        
        # Check button clicks
        action = self.input_handler.handle_button_click(pos, button_rects)
        
        if action == "white":
            self.selected_color = chess.WHITE
        elif action == "black":
            self.selected_color = chess.BLACK
        elif action == "start":
            self._start_game(self.selected_color)
        
        return True  # Continue running
    
    def _start_game(self, color: chess.Color) -> None:
        """Start a new game with the specified color."""
        print(f"[DEBUG START] Starting game with color: {chess.COLOR_NAMES[color]}")
        
        # Create new game state with all required attributes
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
        
        self._update_suggestions()

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
            self.trap_service.all_traps = self.trap_repository.get_all_traps()
            self._update_suggestions()

        # Creăm și afișăm fereastra de dialog
        dialog = QtImportWindow(self.settings_service, start_import_logic, self._clear_database)
        # .exec() o face modală, dar stabilă datorită integrării Qt
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