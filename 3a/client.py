import socket
import threading
import time
import subprocess
import re
import pyaudio
import curses
from curses import wrapper
import os

SERVER_HOST = 'localhost'
SERVER_PORT = 1234
SESSION_ID = None 

def send_request(data):
    """Helper to send short control strings and return response"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((SERVER_HOST, SERVER_PORT))
        s.send(data.encode('utf-8'))
        response = s.recv(4096).decode('utf-8')
        return response
    except Exception as e:
        return f"[Error]: {e}"
    finally:
        s.close()

def authenticate():
    global SESSION_ID
    print("\n--- User Authentication ---")
    uid = input("Enter UserID: ")
    nm = input("Enter Username: ")
    pwd = input("Enter Password: ")
    auth_data = f"AUTH:{uid},{nm},{pwd}" 
    
    response = send_request(auth_data)
    if "Successful" in response and "SID:" in response:
        parts = response.split("SID:")
        print(f"\n[Server]: {parts[0].strip()}")
        SESSION_ID = parts[1].strip()
    else:
        print(f"\n[Server Response]: {response}")
    input("\nPress Enter to return to main menu...")

def view_library():
    if not SESSION_ID: return print("Authenticate first!")
    print("\n--- Available Music Library ---")
    print(send_request(f"GET_LIB:{SESSION_ID}"))
    
    tid = input("\nEnter Track ID to queue (or press Enter to cancel): ")
    if tid.isdigit():
        resp = send_request(f"SET_TRACK:{SESSION_ID},{tid}")
        print(f"[Server]: {resp}")
        if "Track set" in resp:
            print("Now launching Media Player...")
            time.sleep(1)
            wrapper(stream_ui)
    else:
        input("\nPress Enter to return to main menu...")

def view_history():
    if not SESSION_ID: return print("Authenticate first!")
    print("\n--- Your Listening History ---")
    print(send_request(f"GET_HIST:{SESSION_ID}"))
    input("\nPress Enter to return to main menu...")

def download_youtube():
    print("\n--- Download Audio from YouTube (Batch) ---")
    filepath = input("Enter the path to your .txt file with URLs: ").strip()
    
    if not os.path.exists(filepath):
        print("File not found.")
        input("\nPress Enter to return to main menu...")
        return
        
    try:
        with open(filepath, 'r') as f:
            urls = [line.strip() for line in f.readlines() if line.strip()]
            
        for url in urls:
            print(f"\nSending request for: {url}")
            print(f"[Server]: {send_request(f'DOWNLOAD:{url}')}")
            time.sleep(1) 
    except Exception as e:
        print(f"\n[Error]: {e}")
    input("\nPress Enter to return to main menu...")

def heartbeat_monitor(stdscr, target_host):
    while True:
        try:
            output = subprocess.check_output(['ping', '-n', '1', target_host], text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            rtt_match = re.search(r'time[=<]([\d]+)ms', output, re.IGNORECASE)
            if rtt_match:
                rtt = int(rtt_match.group(1))
                quality = "Excellent" if rtt < 10 else "Good" if rtt < 50 else "Poor"
                stdscr.addstr(6, 1, f"Network Strength: {quality} (Ping: {rtt}ms)   ")
            else:
                stdscr.addstr(6, 1, "Network Status: Timeout                  ")
            stdscr.refresh()
        except Exception:
            stdscr.addstr(6, 1, "Network Status: Server Offline           ")
            stdscr.refresh()
        time.sleep(1)

def stream_audio(control_flags):
    global SESSION_ID
    while control_flags['playing']:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((SERVER_HOST, SERVER_PORT))
            s.send(f"STREAM:{SESSION_ID}".encode('utf-8'))
            
            quality_flag = s.recv(1)
            if quality_flag not in [b'0', b'1']: break 
                
            ch = 1 if quality_flag == b'0' else 2
            rt = 11025 if quality_flag == b'0' else 44100
            
            p = pyaudio.PyAudio()
            CHUNK = 1024
            stream = p.open(format=p.get_format_from_width(2), channels=ch, rate=rt, output=True, frames_per_buffer=CHUNK)
            
            while control_flags['playing']:
                if control_flags['paused']:
                    time.sleep(0.1)
                    continue
                if control_flags['next']:
                    s.send(b"NEXT") 
                    control_flags['next'] = False
                    break
                    
                data = s.recv(4096)
                if not data: break 
                stream.write(data)
                
            stream.stop_stream()
            stream.close()
            p.terminate()
        except Exception:
            time.sleep(1) 
        finally:
            s.close()
            if not control_flags['playing'] or control_flags['next']:
                break 

def stream_ui(stdscr):
    if not SESSION_ID: return print("You must authenticate first!")

    curses.curs_set(0) 
    stdscr.clear()
    stdscr.addstr(0, 1, "--- Media Player ---", curses.A_BOLD)
    stdscr.addstr(2, 1, "Press 'P' to Play")
    stdscr.addstr(3, 1, "Press 'Space' to Pause/Resume")
    stdscr.addstr(4, 1, "Press 'N' to Next Track")
    stdscr.addstr(5, 1, "Press 'Q' to Stop and Exit")
    stdscr.refresh()
    
    threading.Thread(target=heartbeat_monitor, args=(stdscr, SERVER_HOST), daemon=True).start()
    control_flags = {'playing': False, 'paused': False, 'next': False}
    
    while True:
        try: key = stdscr.getkey()
        except: key = None    
            
        if key in ['p', 'P'] and not control_flags['playing']:
            control_flags['playing'] = True
            stdscr.addstr(8, 1, "Status: Playing...                       ")
            stdscr.refresh()
            threading.Thread(target=stream_audio, args=(control_flags,), daemon=True).start()
            
        elif key == ' ':
            control_flags['paused'] = not control_flags['paused']
            status = "Paused...                        " if control_flags['paused'] else "Playing...                       "
            stdscr.addstr(8, 1, f"Status: {status}")
            stdscr.refresh()

        elif key in ['n', 'N'] and control_flags['playing']:
            control_flags['next'] = True
            stdscr.addstr(8, 1, "Status: Skipping to next track...        ")
            stdscr.refresh()
            
        elif key in ['q', 'Q']:
            control_flags['playing'] = False
            break

def main():
    while True:
        print("\n=================================")
        print("    Unified Media Client CLI     ")
        print("=================================")
        print("1. Authenticate / Register")
        print("2. View Library & Play")
        print("3. View Listening History")
        print("4. Download Audio from Youtube (.txt)")
        print("5. Exit")
        
        choice = input("\nSelect an option: ")
        
        if choice == '1': authenticate()
        elif choice == '2': view_library()
        elif choice == '3': view_history()
        elif choice == '4': download_youtube()
        elif choice == '5':
            print("Exiting client. Goodbye!")
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()