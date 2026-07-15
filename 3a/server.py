import socket
import threading
import datetime
import subprocess
import re
import time
import os
import yt_dlp
import hashlib
import uuid
import db 

MUSIC_PATH = "music"
CACHE_PATH = "cache"
Max_Limit = 3          
Ban_duration = 15     
Max_conn = 3           

uns = {}               
active_conn = {}       
actct = []          
download_rate_limit = {} 

lock = threading.Lock()       
conn_lock = threading.Lock()  
FFMPEG_SEM = threading.Semaphore(2) 

SESSIONS = {}
ACTIVE_CLIENT_SOCKETS = [] # Track active connections for broadcasting

class ClientState:
    def __init__(self, uid, username, ip_address, session_id):
        self.uid = uid
        self.username = username
        self.ip_address = ip_address
        self.session_id = session_id
        self.current_track = None
        self.chunk_index = 0
        self.queue = []
        self.buffer_health = 100

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def backup_routine():
    """Triggers mysqldump to back up the database instead of copying a file"""
    while True:
        time.sleep(3600) 
        try:
            filename = f"backups/backup_{int(time.time())}.sql"
            subprocess.run(
                [
                    'mysqldump', 
                    '-h', db.DB_CONFIG['host'], 
                    '-u', db.DB_CONFIG['user'], 
                    f"-p{db.DB_CONFIG['password']}", 
                    db.DB_CONFIG['database'], 
                    '-r', filename
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print(f"[System] Database backed up to {filename}")
        except Exception as e:
            print(f"[System] Backup failed: {e}")

def cache_cleanup_routine():
    while True:
        time.sleep(600) 
        now = time.time()
        for f in os.listdir(CACHE_PATH):
            file_path = os.path.join(CACHE_PATH, f)
            if os.path.isfile(file_path) and os.stat(file_path).st_mtime < now - 1800:
                os.remove(file_path)
                print(f"[System] Deleted old cache file: {f}")

def scan_library_routine():
    while True:
        time.sleep(300) 
        conn = db.get_connection()
        if not conn: continue
        
        new_files_added = False
        try:
            with conn.cursor() as c:
                c.execute("START TRANSACTION;")
                for f in os.listdir(MUSIC_PATH):
                    if f.endswith('.mp3') or f.endswith('.wav'):
                        c.execute("SELECT tid FROM Library WHERE filename=%s", (f,))
                        if not c.fetchone():
                            c.execute("INSERT INTO Library (filename, title, added_on) VALUES (%s, %s, %s)",
                                      (f, f.split('.')[0], datetime.datetime.now().isoformat()))
                            new_files_added = True
                conn.commit()
        except:
            conn.rollback()
        finally:
            conn.close()

        if new_files_added:
            print("[System] Broadcasting library update to clients...")
            invalid_sockets = []
            for s in ACTIVE_CLIENT_SOCKETS:
                try:
                    s.send("BROADCAST: Library has been updated! New songs available.\n".encode('utf-8'))
                except Exception:
                    invalid_sockets.append(s)
            for s in invalid_sockets:
                if s in ACTIVE_CLIENT_SOCKETS: ACTIVE_CLIENT_SOCKETS.remove(s)

def is_banned(ip_address):
    conn = db.get_connection()
    if not conn: return False
    
    try:
        with conn.cursor() as c:
            c.execute("SELECT expires_at FROM ActiveBans WHERE ip_address=%s", (ip_address,))
            row = c.fetchone()
            
            if row:
                expires_at = datetime.datetime.fromisoformat(row[0])
                if datetime.datetime.now() < expires_at:
                    return True
                else:
                    c.execute("START TRANSACTION;")
                    c.execute("DELETE FROM ActiveBans WHERE ip_address=%s", (ip_address,))
                    conn.commit()
                    
                    with lock:
                        if ip_address in uns: del uns[ip_address]
                    return False
    except Exception:
        pass
    finally:
        conn.close()
    return False

def ban_ip(ip_address):
    now = datetime.datetime.now()
    expires = now + datetime.timedelta(minutes=Ban_duration)
    conn = db.get_connection()
    if not conn: return
    
    try:
        with conn.cursor() as c:
            c.execute("START TRANSACTION;")
            # MySQL uses REPLACE INTO
            c.execute("REPLACE INTO ActiveBans (ip_address, ban_timestamp, expires_at) VALUES (%s, %s, %s)", 
                      (ip_address, now.isoformat(), expires.isoformat()))
            conn.commit()
    finally:
        conn.close()

def download_audio(url, ip_address):
    now = time.time()
    if ip_address in download_rate_limit and now - download_rate_limit[ip_address] < 10:
        return "Rate limit exceeded. Please wait 10s."
    download_rate_limit[ip_address] = now

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'outtmpl': os.path.join(MUSIC_PATH, '%(title)s.%(ext)s'),
        'restrictfilenames': True, 
        'quiet': True, 'no_warnings': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return "Download complete! Server will process it shortly."
    except Exception as e:
        return f"Download failed."

def stream_audio(clientsocket, address, sid):
    if sid not in SESSIONS:
        clientsocket.sendall(b'X') 
        return
        
    state = SESSIONS[sid]
    ip, port = address
    actct.append(ip)
    CHUNK = 1024
    rtt = 0
    
    try:
        output = subprocess.check_output(['ping', '-c', '1', ip], text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        match = re.search(r'time[<=]([\d]+)ms', output, re.IGNORECASE)
        if match: rtt = int(match.group(1))
    except Exception: pass
    
    track_path = os.path.join(MUSIC_PATH, state.current_track) if state.current_track else 'c.wav'
    if not os.path.exists(track_path): track_path = 'c.wav' 
    
    if rtt > 50:
        clientsocket.sendall(b'0')
        cache_file = os.path.join(CACHE_PATH, f"low_{state.current_track}")
        if not os.path.exists(cache_file):
            with FFMPEG_SEM: 
                subprocess.run(['ffmpeg', '-i', track_path, '-f', 'wav', '-ac', '1', '-ar', '11025', cache_file], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target_file = cache_file
        os.utime(target_file, None) 
    else:
        clientsocket.sendall(b'1')
        target_file = track_path

    try:
        with open(target_file, 'rb') as f:
            f.seek(state.chunk_index * CHUNK)
            while True:
                data = f.read(CHUNK)
                if not data: break
                clientsocket.sendall(data)
                state.chunk_index += 1
                
                clientsocket.settimeout(0.01)
                try:
                    cmd = clientsocket.recv(1024)
                    if cmd == b"NEXT":
                        state.chunk_index = 0 
                        break
                except socket.timeout:
                    pass
                clientsocket.settimeout(None)
    except Exception:
        pass 
    finally:
        if ip in actct: actct.remove(ip)

def handle_client(clientsocket, address):
    ip_address = address[0]
    if is_banned(ip_address):
        clientsocket.send("Access Denied: You are temporarily banned.".encode('utf-8'))
        clientsocket.close()
        return
        
    with conn_lock:
        if active_conn.get(ip_address, 0) >= Max_conn:
            clientsocket.send("Connection limit reached.".encode('utf-8'))
            clientsocket.close()
            return
        active_conn[ip_address] = active_conn.get(ip_address, 0) + 1

    ACTIVE_CLIENT_SOCKETS.append(clientsocket)

    try:
        data = clientsocket.recv(1024).decode('utf-8')
        if not data: return

        if data.startswith("AUTH:"):
            uid, nm, pwd = data.replace("AUTH:", "").split(',')
            conn = db.get_connection()
            if not conn: return
            
            with conn.cursor() as c:
                c.execute("SELECT uid FROM Users WHERE uid=%s AND password=%s", (uid, hash_password(pwd)))
                if c.fetchone():
                    sid = str(uuid.uuid4())
                    SESSIONS[sid] = ClientState(uid, nm, ip_address, sid)
                    clientsocket.send(f"Authentication Successful SID:{sid}".encode('utf-8'))
                    with lock:
                        if ip_address in uns: del uns[ip_address]
                else:
                    c.execute("SELECT uid FROM Users WHERE uid=%s", (uid,))
                    if not c.fetchone():
                        c.execute("START TRANSACTION;")
                        c.execute("INSERT INTO Users(uid, username, password) VALUES(%s, %s, %s)", (uid, nm, hash_password(pwd)))
                        conn.commit()
                        clientsocket.send("New user registered. Please login again.".encode('utf-8'))
                    else:
                        with lock:
                            count = uns.get(ip_address, 0) + 1
                            uns[ip_address] = count
                            if count >= Max_Limit:
                                ban_ip(ip_address)
                                clientsocket.send("Banned.".encode('utf-8'))
                            else:
                                clientsocket.send(f"Failed. {Max_Limit - count} attempts left.".encode('utf-8'))
            conn.close()

        elif data.startswith("DOWNLOAD:"):
            clientsocket.send(download_audio(data.replace("DOWNLOAD:", ""), ip_address).encode('utf-8'))

        elif data.startswith("GET_LIB:"):
            sid = data.replace("GET_LIB:", "")
            if sid in SESSIONS:
                conn = db.get_connection()
                if not conn: return
                with conn.cursor() as c:
                    c.execute("SELECT tid, filename FROM Library")
                    res = "\n".join([f"{r[0]}: {r[1]}" for r in c.fetchall()])
                    clientsocket.send((res if res else "Library empty.").encode('utf-8'))
                conn.close()

        elif data.startswith("SET_TRACK:"):
            payload = data.replace("SET_TRACK:", "").split(',')
            sid, tid = payload[0], payload[1]
            if sid in SESSIONS:
                conn = db.get_connection()
                if not conn: return
                with conn.cursor() as c:
                    c.execute("SELECT filename FROM Library WHERE tid=%s", (tid,))
                    res = c.fetchone()
                    if res:
                        SESSIONS[sid].current_track = res[0]
                        SESSIONS[sid].chunk_index = 0
                        
                        c.execute("START TRANSACTION;")
                        c.execute("INSERT INTO History (uid, track_id, listened_on) VALUES (%s, %s, %s)", 
                                  (SESSIONS[sid].uid, tid, datetime.datetime.now().isoformat()))
                        conn.commit()
                        clientsocket.send("Track set.".encode('utf-8'))
                    else:
                        clientsocket.send("Invalid ID.".encode('utf-8'))
                conn.close()

        elif data.startswith("GET_HIST:"):
            sid = data.replace("GET_HIST:", "")
            if sid in SESSIONS:
                conn = db.get_connection()
                if not conn: return
                with conn.cursor() as c:
                    c.execute("""SELECT l.title, h.listened_on FROM History h 
                                 JOIN Library l ON h.track_id = l.tid 
                                 WHERE h.uid=%s ORDER BY h.hid DESC LIMIT 10""", (SESSIONS[sid].uid,))
                    res = "\n".join([f"{r[0]} (on {r[1]})" for r in c.fetchall()])
                    clientsocket.send((res if res else "No history.").encode('utf-8'))
                conn.close()

        elif data.startswith("STREAM:"):
            stream_audio(clientsocket, address, data.replace("STREAM:", ""))

    except Exception as e:
        pass
    finally:
        if clientsocket in ACTIVE_CLIENT_SOCKETS:
            ACTIVE_CLIENT_SOCKETS.remove(clientsocket)
        with conn_lock:
            active_conn[ip_address] -= 1
            if active_conn[ip_address] == 0: del active_conn[ip_address]
        clientsocket.close()           

def start_server():
    db.init_db()
    if not os.path.exists(MUSIC_PATH): os.makedirs(MUSIC_PATH)
    if not os.path.exists(CACHE_PATH): os.makedirs(CACHE_PATH)
    
    threading.Thread(target=backup_routine, daemon=True).start()
    threading.Thread(target=scan_library_routine, daemon=True).start()
    threading.Thread(target=cache_cleanup_routine, daemon=True).start()
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('0.0.0.0', 1234))
    s.listen(5)
    
    print("Combined Media Server running on port 1234...")
    while True:
        clientsocket, address = s.accept()
        threading.Thread(target=handle_client, args=(clientsocket, address)).start()

if __name__ == "__main__":
    start_server()