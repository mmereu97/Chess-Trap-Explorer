import psycopg2
import configparser

print("--- Script de Verificare a Conexiunii ---")

try:
    config = configparser.ConfigParser()
    config.read('config.ini')
    conn_details = config['postgresql']
    
    print(f"Încercare de conectare cu detaliile din config.ini:")
    print(f"  Host: {conn_details.get('host')}")
    print(f"  Port: {conn_details.get('port')}")
    print(f"  DBName: {conn_details.get('dbname')}")
    print(f"  User: {conn_details.get('user')}")
    
    conn = psycopg2.connect(**conn_details)
    cursor = conn.cursor()
    
    print("\n✅ CONEXIUNE REUȘITĂ!")
    
    # Obținem versiunea serverului
    cursor.execute("SELECT version();")
    server_version = cursor.fetchone()[0]
    print(f"\nVersiune Server: {server_version}")
    
    # Obținem numele bazei de date curente
    cursor.execute("SELECT current_database();")
    db_name = cursor.fetchone()[0]
    print(f"Nume Bază de Date: {db_name}")

    # Obținem utilizatorul curent
    cursor.execute("SELECT current_user;")
    user_name = cursor.fetchone()[0]
    print(f"Utilizator: {user_name}")

    # Obținem portul pe care ascultă serverul
    cursor.execute("SHOW port;")
    port = cursor.fetchone()[0]
    print(f"Port: {port}")

except Exception as e:
    print(f"\n❌ EROARE LA CONECTARE: {e}")

finally:
    if 'conn' in locals() and conn:
        conn.close()