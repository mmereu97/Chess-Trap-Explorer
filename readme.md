# Chess Trap Explorer / Antrenor de Capcane de Șah

Un instrument interactiv pentru învățarea și înregistrarea capcanelor de șah, dezvoltat în Python cu Pygame.

![Screenshot aplicație](Capture.PNG) 

## 📋 Caracteristici

### 🎯 Antrenor de Capcane
- **Joacă cu Albele sau Negrele** - Alege culoarea preferată
- **Sugestii automate** - Programul îți sugerează mutările din capcanele cunoscute
- **Evidențiere vizuală** - Mutările recomandate și țintele sunt evidențiate pe tablă
- **Biblioteca extensivă** - Suportă capcane stocate în Excel

### 📝 Înregistrare de Capcane
- **Mod înregistrare** - Creează capcane noi jucând ambele părți
- **Salvare în Excel** - Stochează capcanele în format organizat
- **Import PGN** - Importă capcane din fișiere PGN (inclusiv Lichess Studies)
- **Gestionare duplicate** - Verifică automat pentru capcane similare

### 🎮 Interfață Intuitivă
- **Tablă interactivă** - Drag & drop pentru mutări
- **Coordonate** - Afișare file și rânduri (a-h, 1-8)
- **Istoric mutări** - Vizualizează și copiază secvența de mutări
- **Butoane functionale** - Undo, Restart, Import, Record

## 🚀 Instalare

### Dependințe Necesare
```bash
pip install pygame chess pandas openpyxl pyperclip pygame-textinput
```

### Fișiere Necesare
1. **Script principal**: `chess_trap_explorer.py`
2. **Fișier capcane**: `traps.xlsx` (se creează automat)
3. **Folder imagini**: `pieces/` cu imaginile pieselor (opțional)

### Structura Folderului
```
chess-trap-explorer/
├── chess_trap_explorer.py
├── traps.xlsx
├── pieces/
│   ├── wK.png, wQ.png, wR.png, wB.png, wN.png, wP.png
│   └── bK.png, bQ.png, bR.png, bB.png, bN.png, bP.png
└── README.md
```

## 📖 Utilizare

### Pornirea Programului
```bash
python chess_trap_explorer.py
```

### Modul de Antrenament
1. **Selectează culoarea** (Albe/Negre) în meniul principal
2. **Joacă mutările** - Trage piesele pe tablă
3. **Urmărește sugestiile** din panoul din dreapta
4. **Observă evidențierile**:
   - 🟩 **Verde**: Mutări recomandate/ținte
   - 🟦 **Albastru**: Mutarea selectată din listă

### Înregistrarea Capcanelor
1. **Apasă "Înregistrează Linie"** pentru a intra în modul record
2. **Joacă ambele părți** pentru a crea capcana
3. **Completează numele** și **numărul rândului** pentru salvare
4. **Apasă din nou butonul** pentru a salva în Excel

### Import din PGN
1. **Apasă "Import PGN"**
2. **Selectează fișierul** .pgn
3. **Setează limita de mutări** (recomandat: 20-30)
4. Capcanele se salvează automat în `traps.xlsx`

## 📊 Format Excel

### Structura Fișierului `traps.xlsx`
- **Sheet "White"**: Capcane pentru jucătorul cu albele
- **Sheet "Black"**: Capcane pentru jucătorul cu negrele

### Format Rânduri
| denumirea | white | black | white | black | ... |
|-----------|-------|-------|-------|-------|-----|
| Scholar's Mate | e4 | e5 | Bc4 | Nc6 | Qh5 | ... |
| Italian Trap | e4 | e5 | Nf3 | Nc6 | Bc4 | ... |

## 🎯 Tipuri de Capcane Suportate

### Capcane de Deschidere
- **Scholar's Mate** (Mat în 4 mutări)
- **Légal's Mate** (Sacrificiu de damă)
- **Italian Game Traps** (Capcane în Italiana)
- **French Defense Traps** (Capcane în Franceză)

### Capcane de Mijloc
- **Pin Tactics** (Ținte și clouări)
- **Fork Traps** (Capcane cu furci)
- **Discovery Attacks** (Atacuri prin descoperire)

### Import din Lichess Studies
- Suportă **Lichess Studies** în format PGN
- Detectează automat **maturile** (#)
- Organizează capcanele pe **culori**

## 🎨 Personalizare

### Culori Tablă
- **Joc Live**: Verde închis/Crem
- **Mod Înregistrare**: Maro clasic

### Evidențieri
- **Verde**: Mutări așteptate/recomandate
- **Roșu**: Mutări periculoase/ținte
- **Albastru**: Selecție utilizator

## 🐛 Troubleshooting

### Probleme Comune
1. **Imaginile pieselor nu se încarcă**
   - Verifică existența folderului `pieces/`
   - Programul folosește fallback text dacă lipsesc imaginile

2. **Excel nu se salvează**
   - Verifică permisiunile de scriere
   - Închide Excel dacă ai fișierul deschis

3. **Import PGN eșuează**
   - Verifică formatul fișierului PGN
   - Unele PGN-uri au encoding diferit

### Dependințe Opționale
- **tkinter**: Pentru dialoguri de fișiere (inclus în Python)
- **Imagini piese**: Fallback la text dacă lipsesc

## 🤝 Contribuții

Contribuțiile sunt binevenite! Te rog să:
1. **Fork** repository-ul
2. **Creează** o nouă branc pentru feature
3. **Commit** modificările
4. **Trimite** pull request

## 📝 Licență

Acest proiect este open source. Folosește-l liber pentru învățare și îmbunătățire.

## 🎓 Despre

Dezvoltat pentru pasionații de șah care vor să-și îmbunătățească cunoștințele de capcane și tactici. Ideal pentru:
- **Începători** care învață capcanele de bază
- **Jucători intermediari** care vor să-și extindă repertoriul
- **Antrenori** care creează materiale de studiu
- **Cluburi de șah** pentru sesiuni de antrenament

---

**Mult succes la șah! ♟️**