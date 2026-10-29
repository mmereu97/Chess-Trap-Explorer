# ♟️ Chess Trap Trainer

**Chess Trap Trainer** is an advanced desktop application written in Python, designed to help chess players learn, practice and explore a wide variety of tactical traps and openings.

![Application screenshot](Capture.PNG)

## ✨ Key Features

### 🎯 **Smart, Context-Aware Training**
- **Dual Trap System**: the app manages two kinds of repertoires:
    1.  **Main Library (PGN)**: a massive database, populated by scanning thousands of games, focused on traps that lead to checkmate.
    2.  **Custom Repertoire (Manually Recorded)**: your personal traps, recorded directly in the app, targeting both **checkmate** and **decisive material wins** (e.g. queen captures, royal forks).
- **Real-Time Suggestions**: as you play, the app shows the most promising continuations from both repertoires, prioritising your custom traps.
- **Clear Visual Differentiation**:
    - 🟪 **Purple**: suggestions from your custom repertoire (e.g. `[Queen Hunter]`).
    - 🟦 **Blue**: suggestions from the main checkmate library.
- **Tactical Highlighting**:
    - 🟥 **Red**: highlights the suggested move when you select a trap from the list.
    - 🟩 **Green**: highlights the opponent's expected reply, helping you drill the correct continuation.
- **Transposition Recognition**: the system identifies the position on the board, not just the move sequence. Even if you reach a position through a different move order, you still get the right suggestions.
- **Opening Database**: displays the name of the opening being played in real time (e.g. "Sicilian: Najdorf") and recognises systems such as the "London System" or the "King's Indian Defense".

### ✍️ **Flexible, Powerful Recording Mode**
- **Contextual Recording**: the "Record" button has dual functionality:
    1.  **From Scratch**: starts a recording session on an empty board to enter a new line.
    2.  **Saving the Current Game**: if you are in the middle of an interesting game, press "Record" to save the current game history directly as a new trap.
- **Automatic Analysis**: when recording ends, the system automatically detects the trap type:
    - `Checkmate`
    - `Direct Queen Capture`
    - `Royal Fork` (king + queen)
- **Full Control**: a confirmation dialog lets you **Save**, **Cancel** or **Continue** recording.
- **Navigation While Recording**: use the `back` and `forward` buttons to fix mistakes mid-recording without starting over.

### 🗃️ **Advanced Data Management**
- **Non-Blocking Workflow**: saving custom traps is **instant**. New traps are added dynamically in memory, without freezing the UI.
- **Bulk PGN Import**: import tens of thousands of mate traps from PGN files (including Lichess, chess.com exports, etc.). The process is extremely fast, using every CPU core.
- **Database Management**:
    - **Import**: from a single PGN file or an entire folder.
    - **Audit DB**: cleans and repairs the main library (removes duplicates, fixes colours, deletes invalid entries).
    - **Manage Custom Traps**: a dedicated interface to view and selectively delete manually recorded traps.
    - **Database Info**: a statistics window showing library traps and custom-repertoire traps separately.
- **Smart Two-Level Caching**:
    - `trap_index.cache`: the large cache for the PGN library. Rebuilt (a slow process) only after an import or audit.
    - `queen_trap_index.cache`: the small, fast cache for custom traps. Rebuilt **instantly** on every change.

## 🛠️ Software Architecture

The application follows **Clean Architecture** principles, with responsibilities clearly separated into layers for easy maintenance and extension:
- **UI:** `Renderer`, `InputHandler`, and `Qt...` classes for dialog windows.
- **Controller (`GameController`):** orchestrates the data flow and manages application state.
- **Services:** `TrapService` (PGN library), `QueenTrapService` (custom traps), `PGNImportService`, `DatabaseAuditor`, `OpeningDatabase`.
- **Repositories (`TrapRepository`, `QueenTrapRepository`):** abstraction layer over the SQLite database tables.
- **Entities:** `GameState`, `ChessTrap`, `QueenTrap`, `MoveSuggestion`, etc.

## 🚀 Installation

You will need Python 3.8 or newer.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/mmereu97/chess-trap-trainer.git
    cd chess-trap-trainer
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    ```
    *   On Windows, activate it with: `.\venv\Scripts\activate`
    *   On macOS/Linux, activate it with: `source venv/bin/activate`

3.  **Install the dependencies:**
    `requirements.txt` lists everything needed.
    ```bash
    pip install -r requirements.txt
    ```

4.  **Piece images (optional):**
    Make sure there is a `pieces` folder in the root directory containing the chess piece images as PNGs (e.g. `wp.png` for the white pawn, `bn.png` for the black knight). If the folder or images are missing, the program falls back to simple geometric pieces.

### 📁 Project Structure
```
chess-trap-trainer/
├── Chess_trap_explorer.py  # Main application script
├── chess_traps.db          # SQLite database (created automatically)
├── trap_index.cache        # PGN library cache (created automatically)
├── queen_trap_index.cache  # Custom trap cache (created automatically)
├── requirements.txt        # Dependency list
├── pieces/                 # Chess piece images
│   ├── wK.png, wQ.png, ...
│   └── bK.png, bQ.png, ...
└── README.md
```

## 📖 Usage

Start the application by running the main script:
```bash
python Chess_trap_explorer.py
```

### Recommended workflow:

1.  **Populate the Main Library (optional):** for a large checkmate repertoire, go to `Controls` -> `Import / Audit`, select a PGN file or folder and start the import.
2.  **Start Training:** the app opens straight into a game. Use "Play as White/Black" to switch colours; "Reset Game" starts a new game with the same colour.
3.  **Explore and Learn:**
    *   Make moves on the board.
    *   The right-hand panel shows suggestions, with custom ones (purple) taking priority.
    *   Click a suggestion to highlight it on the board. Make the move and watch the green highlight showing the opponent's likely reply.
4.  **Build Your Repertoire:**
    *   Press "Record New Trap" to enter recording mode on an empty board.
    *   Play the line you want (use the navigation buttons to correct mistakes).
    *   Press "Confirm/Stop" and choose to save. The trap is available instantly.
    *   Played an interesting line in a normal game? Press "Record New Trap" to save it directly.

## 📦 Dependencies

The project relies on the following Python libraries:

*   `pygame`: the graphics engine and main chessboard interface.
*   `python-chess`: all chess logic (moves, validation, PGN, FEN).
*   `PySide6`: native dialog windows (import, confirmations, statistics).
*   `pyperclip`: the "Copy PGN" button.

## 🤝 Contributing

Contributions are welcome! Please follow this workflow:
1.  **Fork** this repository.
2.  **Create** a branch for your feature (`git checkout -b feature/FeatureName`).
3.  **Commit** your changes (`git commit -am 'Add some feature'`).
4.  **Push** the branch (`git push origin feature/FeatureName`).
5.  **Open** a Pull Request.

---

**Good luck at the board!**
