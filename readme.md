# ♟️ Chess Trap Trainer

**Chess Trap Trainer** este o aplicație desktop avansată, dezvoltată în Python, concepută pentru a ajuta jucătorii de șah să învețe, să practice și să exploreze o varietate largă de capcane și deschideri.

![Screenshot aplicație](Capture.PNG) 

## ✨ Funcționalități Principale

### 🎯 **Antrenament Inteligent**
- **Joacă cu Albele sau Negrele**: Alege culoarea preferată pentru a începe antrenamentul.
- **Sugestii în Timp Real**: Aplicația îți arată cele mai promițătoare continuări din baza sa de date.
- **Recunoașterea Transpozițiilor**: Sistemul identifică poziția de pe tablă, nu doar secvența de mutări. Chiar dacă ajungi la o poziție printr-o ordine diferită de mutări, vei primi sugestiile corecte.
- **Evidențiere Vizuală**:
  - 🟥 **Roșu**: Evidențiază mutarea sugerată când selectezi o capcană din listă.
  - 🟩 **Verde**: Evidențiază cel mai comun răspuns al adversarului, ajutându-te să anticipezi.
- **Bază de Date a Deschiderilor**: Afișează în timp real numele deschiderii care se joacă (ex: "Sicilian: Najdorf"), împreună cu codul ECO corespunzător.

### 🗃️ **Management Avansat al Datelor**
- **Import Masiv de PGN-uri**: Importă mii de capcane din fișiere PGN (inclusiv de pe Lichess, chess.com, etc.). Procesul este extrem de rapid, folosind toate nucleele procesorului.
- **Gestionare Bază de Date**:
    - Importă dintr-un singur fișier PGN sau dintr-un folder întreg.
    - Funcție de **Audit DB** pentru a curăța și repara baza de date (elimină duplicate, corectează culorile, șterge intrările invalide).
    - Opțiune de a șterge complet baza de date.
- **Caching Inteligent**: Indexul de poziții este salvat pe disc (`trap_index.cache`) pentru o pornire aproape instantanee a aplicației. Cache-ul este invalidat și reconstruit automat doar dacă baza de date a fost modificată (după un import sau audit).

### ✍️ **Înregistrare și Navigare**
- **Mod Înregistrare**: Creează și salvează propriile capcane direct în baza de date SQLite.
- **Istoric Complet**: Vizualizează istoricul partidei și copiază-l în clipboard cu un singur click.
- **Navigare în Partidă**: Sari la început, la sfârșit, sau navighează mutare cu mutare.

## 🛠️ Arhitectură Software

Aplicația este construită folosind principii de **Clean Architecture**, separând clar responsabilitățile în straturi distincte pentru o mentenanță și extindere ușoară:
- **UI (Interfață Utilizator):** `Renderer`, `InputHandler`, `QtImportWindow`
- **Controller (`GameController`):** Ordonează fluxul de date.
- **Services (Servicii):** `TrapService`, `PGNImportService`, `DatabaseAuditor`, `OpeningDatabase`
- **Repository (`TrapRepository`):** Strat de abstractizare peste baza de date SQLite.
- **Entities (Entități):** `ChessTrap`, `GameState`, `MoveSuggestion`, etc.

## 🚀 Instalare

Pentru a rula acest proiect, vei avea nevoie de Python 3.8 sau o versiune mai nouă.

1.  **Clonează repository-ul:**
    ```bash
    git clone https://github.com/your-username/chess-trap-trainer.git
    cd chess-trap-trainer
    ```

2.  **Creează un mediu virtual (recomandat):**
    ```bash
    python -m venv venv
    ```
    *   Pe Windows, activează-l cu: `.\venv\Scripts\activate`
    *   Pe macOS/Linux, activează-l cu: `source venv/bin/activate`

3.  **Instalează dependențele:**
    Fișierul `requirements.txt` conține toate pachetele necesare.
    ```bash
    pip install -r requirements.txt
    ```

4.  **Imagini piese (opțional):**
    Asigură-te că ai un folder numit `pieces` în directorul rădăcină, care conține imaginile pieselor de șah în format PNG (ex: `wp.png` pentru pion alb, `bn.png` pentru cal negru). Dacă folderul sau imaginile lipsesc, programul va afișa piese simple, geometrice.

### 📁 Structura Proiectului
```
chess-trap-trainer/
├── "B Claude .py"          # Scriptul principal al aplicației
├── chess_traps.db          # Baza de date SQLite (se creează automat)
├── trap_index.cache        # Fișierul de cache (se creează automat)
├── requirements.txt        # Lista de dependențe
├── pieces/                 # Folder cu imaginile pieselor
│   ├── wK.png, wQ.png, ...
│   └── bK.png, bQ.png, ...
└── README.md
```

## 📖 Utilizare

Pentru a porni aplicația, rulează scriptul principal:
```bash
python "B Claude .py"
```

### Flux de lucru recomandat:

1.  **Populează Baza de Date:** La prima utilizare, aplicația va fi goală. Mergi la `Controls` -> `Import PGN`. Selectează un fișier PGN sau un folder care conține partide terminate cu mat pentru a popula baza de date. Cu cât mai multe partide, cu atât mai "inteligentă" va fi aplicația.
2.  **Rulează Audit (Opțional):** După un import masiv, este o idee bună să rulezi `Audit DB` pentru a curăța și optimiza baza de date.
3.  **Începe Antrenamentul:** Din meniul principal, alege culoarea cu care vrei să joci și apasă `Start Game`.
4.  **Explorează și Învață:**
    *   Fă mutări pe tablă.
    *   Panoul din dreapta îți va arăta sugestii de mutări din capcanele cunoscute, sortate după popularitate.
    *   Click pe o sugestie pentru a o evidenția pe tablă.
    *   Fă mutarea și observă highlight-ul verde care indică răspunsul probabil al adversarului.

## 📦 Dependențe

Proiectul se bazează pe următoarele biblioteci Python:

*   `pygame`: Pentru motorul grafic și interfața principală a tablei de șah.
*   `python-chess`: Pentru toată logica de șah (mutări, validări, PGN, FEN).
*   `PySide6`: Pentru ferestrele de dialog native (import, mesaje de confirmare, audit).
*   `pygame-textinput`: Pentru câmpul de introducere a numelui capcanei în modul de înregistrare.
*   `pyperclip`: Pentru funcționalitatea butonului "Copy" din panoul de istoric.

## 🤝 Contribuții

Contribuțiile sunt binevenite! Te rog să respecți următorul flux de lucru:
1.  **Fork** acest repository.
2.  **Creează** o nouă branch pentru funcționalitatea ta (`git checkout -b feature/NumeFeature`).
3.  **Commit** modificările tale (`git commit -am 'Add some feature'`).
4.  **Push** către branch (`git push origin feature/NumeFeature`).
5.  **Deschide** un Pull Request.

---

**Mult succes la șah!**