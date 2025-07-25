import itertools
import string
import psycopg2
import configparser

print("--- Începe scriptul de creare/verificare a partițiilor ---")

# Caracterele posibile în prima parte a unui FEN
# p,n,b,r,q,k (litere mici și mari), 1-8, și /
fen_chars = 'pnbrqkPNBRQK12345678/'
total_combinations = len(fen_chars) ** 3
created_count = 0
skipped_count = 0

# Generează toate combinațiile posibile de 3 caractere
combinations = itertools.product(fen_chars, repeat=3)

# --- Detalii Conexiune Bază de Date ---
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
    print(f"✅ Conectat la PostgreSQL (baza de date: {conn_details['dbname']})")

    # Folosim un singur cursor pentru performanță
    with conn.cursor() as cursor:
        for i, combo_tuple in enumerate(combinations):
            combo_str = "".join(combo_tuple)
            table_name_suffix = combo_str.replace('/', '_slash')
            table_name = f"position_index_{table_name_suffix}"
            
            sql_command = f"CREATE TABLE IF NOT EXISTS {table_name} PARTITION OF position_index FOR VALUES IN ('{combo_str}');"
            
            try:
                cursor.execute(sql_command)
                # Verificăm dacă s-a creat ceva nou
                if cursor.statusmessage == "CREATE TABLE":
                    created_count += 1
                    print(f"({i+1}/{total_combinations}) Partiție NOUĂ creată pentru: '{combo_str}'")
                else:
                    skipped_count += 1
                
                # Afișăm un progres mai rar pentru a nu umple consola
                if (i + 1) % 1000 == 0:
                    print(f"   ... procesat {i+1}/{total_combinations} ...")

            except Exception as e:
                print(f"❌ Eroare la crearea partiției pentru '{combo_str}': {e}")
                conn.rollback()
                break # Oprim la prima eroare gravă

    conn.commit()
    print("\n--- REZUMAT ---")
    print(f"✅ Scriptul a fost finalizat cu succes!")
    print(f"Partiții noi adăugate: {created_count}")
    print(f"Partiții existente ignorate: {skipped_count}")
    print(f"Total verificat: {created_count + skipped_count}/{total_combinations}")


except Exception as e:
    print(f"❌ Eroare la conectare sau în timpul execuției: {e}")

finally:
    if 'conn' in locals() and conn and not conn.closed:
        conn.close()
        print("🔌 Conexiunea la baza de date a fost închisă.")