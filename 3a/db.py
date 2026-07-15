import pymysql
import os

# Update these with your actual MySQL credentials
DB_CONFIG = {
    'host': os.getenv('DB_HOST','mysqldb'),
    'user': os.getenv('DB_USER','root'),
    'password': os.getenv('MYSQL_ROOT_PASSWORD','root'), 
    'database': os.getenv('MYSQL_DATABASE','music_server')
}

def get_connection():
    try:
        conn = pymysql.connect(
            host=DB_CONFIG['host'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database']
        )
        return conn
    except Exception as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def init_db():
    # 1. Connect to MySQL server without specifying a database to create it if needed
    try:
        server_conn = pymysql.connect(
            host=DB_CONFIG['host'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        with server_conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        server_conn.close()
    except Exception as e:
        print(f"Failed to create or connect to database server: {e}")
        return

    # 2. Connect to the specific database to create tables
    conn = get_connection()
    if not conn: return
    
    try:
        with conn.cursor() as c:
            c.execute('START TRANSACTION;')
            
            # Users Table
            c.execute('''CREATE TABLE IF NOT EXISTS Users (
                uid VARCHAR(255) PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                password VARCHAR(255) NOT NULL
            )''')
            
            # Centralized Music Library
            c.execute('''CREATE TABLE IF NOT EXISTS Library (
                tid INT AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255) UNIQUE,
                title VARCHAR(255),
                added_on VARCHAR(255)
            )''')
            
            # User Playlists
            c.execute('''CREATE TABLE IF NOT EXISTS Playlists (
                pid INT AUTO_INCREMENT PRIMARY KEY,
                uid VARCHAR(255) NOT NULL,
                playlist_name VARCHAR(255) NOT NULL,
                track_id INT NOT NULL,
                FOREIGN KEY(uid) REFERENCES Users(uid),
                FOREIGN KEY(track_id) REFERENCES Library(tid)
            )''')
            
            # Listening History
            c.execute('''CREATE TABLE IF NOT EXISTS History (
                hid INT AUTO_INCREMENT PRIMARY KEY,
                uid VARCHAR(255) NOT NULL,
                track_id INT NOT NULL,
                listened_on VARCHAR(255) NOT NULL,
                FOREIGN KEY(uid) REFERENCES Users(uid),
                FOREIGN KEY(track_id) REFERENCES Library(tid)
            )''')

            # State and Bans
            c.execute('''CREATE TABLE IF NOT EXISTS UserState (
                uid VARCHAR(255) PRIMARY KEY,
                username VARCHAR(255),
                ip_address VARCHAR(255),
                last_seen DATETIME,
                is_active TINYINT DEFAULT 1
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS ActiveBans (
                ip_address VARCHAR(255) PRIMARY KEY,
                ban_timestamp VARCHAR(255),
                expires_at VARCHAR(255)
            )''')
            
        conn.commit()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Database Initialization Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()