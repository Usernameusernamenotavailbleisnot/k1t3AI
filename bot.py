import requests
import time
import datetime
import json
import sys
import random
import concurrent.futures
from colorama import init, Fore, Style, Back
from eth_account import Account
from eth_account.messages import encode_defunct
from threading import Thread, Lock
from requests.exceptions import RequestException, ProxyError, SSLError, ConnectionError, Timeout
from fake_useragent import UserAgent
import os
from datetime import datetime, timedelta
from web3 import Web3
from pathlib import Path

init(autoreset=True)

# Global configurations
USE_PROXY = False
proxies_list = []
PROFESSOR_AGENT_ID = "deployment_vxJKb0YqfT5VLWZU7okKWa8L"
FAUCET_URL = "https://faucet.gokite.ai/api/sendToken"
SITE_KEY = "6LeNaK8qAAAAAHLuyTlCrZD_U1UoFLcCTLoa_69T"
CHAT_TIMEOUT = 25 * 3600  # 25 hours in seconds
print_lock = Lock()
CHAT_HISTORY_FILE = "chat_history.json"

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2
RETRY_MULTIPLIER = 2

def timestamp():
    return "[" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "]"

def safe_print(msg, color=None):
    with print_lock:
        if color:
            print(f"{timestamp()} {color}{msg}{Style.RESET_ALL}")
        else:
            print(f"{timestamp()} {msg}")

def log_info(msg):
    safe_print(msg, Fore.BLUE)

def log_success(msg):
    safe_print(msg, Fore.GREEN)

def log_error(msg):
    safe_print(msg, Fore.RED)

def log_warning(msg):
    safe_print(msg, Fore.YELLOW)

class RequestHeaders:
    @staticmethod
    def get_base_headers():
        ua = UserAgent()
        return {
            "accept-language": "en-US,en;q=0.9",
            "priority": "u=1, i",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "user-agent": ua.random
        }

    @staticmethod
    def get_kite_headers():
        headers = RequestHeaders.get_base_headers()
        headers.update({
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://testnet.gokite.ai",
            "referer": "https://testnet.gokite.ai/"
        })
        return headers

    @staticmethod
    def get_professor_headers():
        headers = RequestHeaders.get_base_headers()
        headers.update({
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://agents.testnet.gokite.ai",
            "referer": "https://agents.testnet.gokite.ai/"
        })
        return headers

class ChatHistory:
    def __init__(self):
        # Simplified version that always allows chatting
        pass

    def can_chat(self, wallet_address):
        # Always return True, allowing continuous chatting
        return True

    def update_last_chat(self, wallet_address):
        # No-op method, just to maintain interface compatibility
        pass

    def time_until_next_chat(self, wallet_address):
        # Always return 0, indicating no wait time
        return 0

def get_wallet_address(private_key):
    try:
        account = Account.from_key(private_key)
        return account.address
    except Exception as e:
        log_error(f"Error deriving wallet address: {e}")
        return None

def load_proxies():
    global USE_PROXY, proxies_list
    try:
        with open("proxy.txt", "r", encoding="utf-8") as f:
            proxies_list = [line.strip() for line in f if line.strip()]
        if proxies_list:
            USE_PROXY = True
            log_success(f"Loaded {len(proxies_list)} proxies")
        else:
            log_error("No proxies found in proxy.txt")
    except Exception as e:
        log_error(f"Error loading proxies: {e}")
        USE_PROXY = False

def get_proxies():
    if USE_PROXY and proxies_list:
        proxy = random.choice(proxies_list)
        return {"http": proxy, "https": proxy}
    return None

def make_request(method, url, headers=None, json=None, use_proxy=True, max_retries=MAX_RETRIES):
    current_retry = 0
    delay = RETRY_DELAY

    while current_retry <= max_retries:
        try:
            proxies = get_proxies() if use_proxy and USE_PROXY else None
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                proxies=proxies,
                timeout=300
            )
            
            # For authentication endpoints, don't raise_for_status to handle the response 
            # even if it's a 400 or other error
            if 'auth/eth' in url:
                return response
                
            response.raise_for_status()
            return response

        except ProxyError as e:
            log_error(f"Proxy error: {e}")
            if USE_PROXY and proxies_list:
                continue
            break

        except (ConnectionError, Timeout) as e:
            log_error(f"Connection error: {e}")

        except RequestException as e:
            log_error(f"Request error: {e}")

        if current_retry == max_retries:
            break

        current_retry += 1
        log_info(f"Retrying request ({current_retry}/{max_retries}) after {delay}s...")
        time.sleep(delay)
        delay *= RETRY_MULTIPLIER

    raise RequestException(f"Failed after {max_retries} retries")

def load_private_keys():
    try:
        with open("pk.txt", "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        log_error(f"Error reading pk.txt: {e}")
        return []

def get_auth_ticket(nonce):
    url = "https://api-kiteai.bonusblock.io/api/auth/get-auth-ticket"
    headers = RequestHeaders.get_kite_headers()
    
    try:
        response = make_request("POST", url, headers=headers, json={"nonce": f"timestamp_{nonce}"})
        
        # Check for non-JSON response
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            return {"error": "Non-JSON response", "payload": "", "success": False}
            
        # Try to parse JSON response safely
        try:
            data = response.json()
            return data
        except json.JSONDecodeError as je:
            log_error(f"JSON decode error: {je}")
            return {"error": "Invalid JSON", "payload": "", "success": False}
            
    except Exception as e:
        log_error(f"Error in get-auth-ticket: {e}")
        return {"error": str(e), "payload": "", "success": False}

def sign_payload(payload, private_key):
    try:
        message = encode_defunct(text=payload)
        signed = Account.sign_message(message, private_key=private_key)
        signature = signed.signature.hex()
        return "0x" + signature if not signature.startswith("0x") else signature
    except Exception as e:
        log_error(f"Error signing payload: {e}")
        return None

def eth_auth(signed_message, nonce):
    url = "https://api-kiteai.bonusblock.io/api/auth/eth"
    headers = RequestHeaders.get_kite_headers()
    body = {
        "blockchainName": "ethereum",
        "signedMessage": signed_message,
        "nonce": f"timestamp_{nonce}",
        "referralId": "Cz4gdkBf"
    }
    
    try:
        response = make_request("POST", url, headers=headers, json=body)
        
        # Try to parse response even if it's an error status code
        try:
            data = response.json()
            
            if response.status_code != 200:
                return None, None
                
            if data.get("success") and data.get("payload"):
                if "session" in data["payload"] and "token" in data["payload"]["session"]:
                    token = data["payload"]["session"]["token"]
                    user_id = data["payload"]["account"]["userId"]
                    return token, user_id
            return None, None
        except json.JSONDecodeError:
            return None, None
    except Exception as e:
        log_error(f"Error in eth auth: {e}")
        return None, None

def complete_mission(token, mission_type):
    urls = {
        "social": "https://api-kiteai.bonusblock.io/api/forward-link/go/kiteai-mission-social-3",
        "tutorial": "https://api-kiteai.bonusblock.io/api/forward-link/go/kiteai-mission-tutorial-1"
    }
    url = urls.get(mission_type)
    if not url:
        return False

    headers = RequestHeaders.get_kite_headers()
    headers["x-auth-token"] = token
    
    try:
        response = make_request("POST", url, headers=headers)
        return response.status_code == 200
    except Exception as e:
        log_error(f"Error completing {mission_type} mission: {e}")
        return False

def generate_random_question():
    import random
    
    # Generate random transaction hash (64 characters after 0x)
    tx_hash = '0x' + ''.join(random.choices('0123456789abcdef', k=64))
    
    # Simple question
    question = f"What is Kite AI?"
    
    return question

def solve_captcha(capsolver_api_key):
    log_info("Solving Captcha...")
    try:
        task_payload = {
            "clientKey": capsolver_api_key,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": "https://faucet.gokite.ai",
                "websiteKey": SITE_KEY
            }
        }
        
        create_task = requests.post("https://api.capsolver.com/createTask", json=task_payload)
        if create_task.status_code != 200:
            raise Exception("Failed to create captcha task")
        
        task_id = create_task.json().get("taskId")
        
        while True:
            get_result = requests.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": capsolver_api_key, "taskId": task_id}
            )
            result = get_result.json()
            
            if result.get("status") == "ready":
                log_success("Captcha solved!")
                return result.get("solution").get("gRecaptchaResponse")
            elif result.get("status") == "failed":
                raise Exception("Failed to solve captcha")
                
            time.sleep(3)
            
    except Exception as e:
        log_error(f"Captcha Error: {str(e)}")
        return None

def claim_faucet(wallet_address, capsolver_api_key):
    try:
        captcha_token = solve_captcha(capsolver_api_key)
        if not captcha_token:
            return None

        payload = {
            "address": wallet_address,
            "token": "",
            "v2Token": captcha_token,
            "chain": "KITE",
            "couponId": ""
        }

        headers = RequestHeaders.get_kite_headers()
        proxy = get_proxies() if USE_PROXY else None
        
        response = requests.post(FAUCET_URL, json=payload, headers=headers, proxies=proxy)
        result = response.json()
        
        if "txHash" in result:
            log_success(f"Faucet claim successful for {wallet_address}! TX: {result['txHash']}")
            return result
        else:
            log_error(f"Faucet claim failed: {result.get('message', 'Unknown error')}")
            return None

    except Exception as e:
        log_error(f"Error claiming faucet: {str(e)}")
        return None

def report_chat_usage(wallet_address, question, response, max_retries=3):
    url = "https://quests-usage-dev.prod.zettablock.com/api/report_usage"
    headers = RequestHeaders.get_kite_headers()
    payload = {
        "wallet_address": wallet_address.lower(),
        "agent_id": PROFESSOR_AGENT_ID,
        "request_text": question,
        "response_text": response,
        "request_metadata": {}
    }
    
    current_retry = 0
    delay = RETRY_DELAY
    
    while current_retry <= max_retries:
        try:
            response = make_request(
                method="POST",
                url=url,
                headers=headers,
                json=payload,
                use_proxy=True
            )
            
            if response.status_code == 200:
                log_success("Chat usage reported successfully")
                return True
            else:
                raise RequestException(f"Report usage returned status code: {response.status_code}")
                
        except Exception as e:
            log_warning(f"Failed to report usage (attempt {current_retry + 1}/{max_retries}): {e}")
            
            if current_retry == max_retries:
                log_warning("Max retries reached for report usage")
                return True  # Still return True to continue the main flow
                
            current_retry += 1
            log_info(f"Retrying report usage in {delay}s...")
            time.sleep(delay)
            delay *= RETRY_MULTIPLIER
            
    return True  # Continue despite reporting failure

def chat_with_professor(wallet_address, question, chat_history):
    if not chat_history.can_chat(wallet_address):
        remaining_time = chat_history.time_until_next_chat(wallet_address)
        log_warning(f"Chat cooldown active. Next chat available in: {format_time(remaining_time)}")
        return None

    url = f"https://deployment-vxjkb0yqft5vlwzu7okkwa8l.stag-vxzy.zettablock.com/main"
    headers = RequestHeaders.get_professor_headers()
    payload = {
        "message": question,
        "stream": True
    }
    
    try:
        # Make request with stream=True in requests
        response = requests.post(url, headers=headers, json=payload, stream=True)
        response.raise_for_status()
        
        full_response = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data: '):
                    try:
                        # Remove 'data: ' prefix and parse JSON
                        json_str = decoded_line[6:]
                        if json_str.strip() == '[DONE]':
                            break
                        data = json.loads(json_str)
                        if "choices" in data and data["choices"]:
                            chunk = data["choices"][0]["delta"].get("content", "")
                            if chunk:
                                full_response += chunk
                    except json.JSONDecodeError:
                        continue
        
        if full_response:
            report_chat_usage(wallet_address, question, full_response)
            chat_history.update_last_chat(wallet_address)
            return full_response
        return None
            
    except Exception as e:
        log_error(f"Error in chat: {e}")
        return None

def process_chat_continuous(private_key, iterations):
    try:
        wallet_address = get_wallet_address(private_key)
        if not wallet_address:
            log_error("Failed to derive wallet address")
            return False

        chat_history = ChatHistory()

        while True:  # Continuous loop
            log_success(f"Starting new chat cycle for wallet: {wallet_address}")
            
            # Perform chat interactions
            for i in range(iterations):
                if chat_history.can_chat(wallet_address):
                    question = generate_random_question()
                    
                    answer = chat_with_professor(wallet_address, question, chat_history)
                    if answer:
                        log_success("Chat interaction successful")
                    else:
                        log_error("Chat interaction failed")
                
                if i < iterations - 1:
                    time.sleep(5)
            
            # Calculate and display next chat time
            next_chat_time = datetime.now() + timedelta(hours=25)
            log_success(f"Chat cycle completed. Next cycle at: {next_chat_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Start countdown timer
            countdown_start = time.time()
            countdown_duration = 25 * 3600  # 25 hours in seconds
            
            while time.time() - countdown_start < countdown_duration:
                remaining = countdown_duration - (time.time() - countdown_start)
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                seconds = int(remaining % 60)
                
                # Clear previous line and update countdown
                with print_lock:
                    sys.stdout.write(f"\r{Fore.YELLOW}Next chat cycle in: {hours:02d}:{minutes:02d}:{seconds:02d}{Style.RESET_ALL}")
                    sys.stdout.flush()
                
                time.sleep(1)  # Update every second
            
            print()  # New line after countdown
            
    except KeyboardInterrupt:
        log_warning("Chat loop interrupted by user")
        return True
    except Exception as e:
        log_error(f"Error in continuous chat process: {e}")
        return False

def process_faucet_claims(private_keys, capsolver_api_key):
    success_count = 0
    for idx, private_key in enumerate(private_keys, 1):
        wallet_address = get_wallet_address(private_key)
        if not wallet_address:
            log_error(f"Failed to derive wallet address for key {idx}")
            continue
            
        log_info(f"Processing faucet claim {idx}/{len(private_keys)} for {wallet_address}")
        result = claim_faucet(wallet_address, capsolver_api_key)
        
        if result:
            success_count += 1
            log_success(f"Successfully claimed faucet for {wallet_address}")
        else:
            log_error(f"Failed to claim faucet for {wallet_address}")
            
        if idx < len(private_keys):
            delay = random.uniform(3, 8)
            log_info(f"Waiting {delay:.1f} seconds before next claim...")
            time.sleep(delay)
    
    return success_count

def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def print_banner():
    banner = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║                 Kite AI Automation Tool                    ║
║           Enhanced with Timeout & Faucet Features         ║
╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)

# Added missing process_registration function
def process_registration(private_key, idx, total):
    wallet_address = get_wallet_address(private_key)
    if not wallet_address:
        log_error(f"Failed to derive wallet address for key {idx}/{total}")
        return False
        
    log_info(f"Processing registration {idx}/{total} for {wallet_address}")
    
    try:
        # Get auth ticket
        nonce = round(time.time() * 1000)
        ticket_response = get_auth_ticket(nonce)
        
        # Check if the response has the expected structure
        if not ticket_response or not isinstance(ticket_response, dict):
            log_error(f"Invalid auth ticket response for {wallet_address}")
            return False
            
        # Handle the case where auth ticket is directly in payload (string)
        if ticket_response.get("success") and isinstance(ticket_response.get("payload"), str):
            auth_ticket = ticket_response["payload"]
        else:
            log_error(f"Failed to get auth ticket for {wallet_address}")
            return False
            
        # Sign message
        signature = sign_payload(auth_ticket, private_key)
        if not signature:
            log_error(f"Failed to sign auth ticket for {wallet_address}")
            return False
            
        # Authenticate
        token, user_id = eth_auth(signature, nonce)
        if not token or not user_id:
            log_error(f"Authentication failed for {wallet_address}")
            return False
            
        log_success(f"Successfully authenticated wallet: {wallet_address}")
        
        # Complete missions
        tutorial_success = complete_mission(token, "tutorial")
        social_success = complete_mission(token, "social")
        
        if tutorial_success and social_success:
            log_success(f"Successfully completed all missions for {wallet_address}")
            return True
        else:
            if not tutorial_success:
                log_error(f"Failed to complete tutorial mission for {wallet_address}")
            if not social_success:
                log_error(f"Failed to complete social mission for {wallet_address}")
            return False
            
    except Exception as e:
        log_error(f"Error in registration process for {wallet_address}: {e}")
        return False

def main():
    print_banner()
    
    # Ask about proxy usage
    use_proxy_input = input(f"{Fore.CYAN}Do you want to use proxies? (yes/no): {Style.RESET_ALL}").strip().lower()
    if use_proxy_input in ['y', 'yes']:
        load_proxies()
    
    while True:
        print(f"\n{Fore.CYAN}Select an option:{Style.RESET_ALL}")
        print("1. Register new accounts and complete missions")
        print("2. Chat interaction with Professor (Continuous 25h loop)")
        print("3. Request faucet tokens")
        print("4. Exit")
        
        choice = input(f"\n{Fore.CYAN}Enter your choice (1-4): {Style.RESET_ALL}").strip()
        
        if choice == "1":
            private_keys = load_private_keys()
            if not private_keys:
                log_error("No private keys found in pk.txt")
                continue
            
            use_threads = input(f"{Fore.CYAN}Use multi-threading? (yes/no): {Style.RESET_ALL}").strip().lower() in ['y', 'yes']
            
            if use_threads:
                max_workers = min(10, len(private_keys))
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [
                        executor.submit(process_registration, key, idx + 1, len(private_keys))
                        for idx, key in enumerate(private_keys)
                    ]
                    concurrent.futures.wait(futures)
            else:
                for idx, key in enumerate(private_keys, 1):
                    process_registration(key, idx, len(private_keys))
                    if idx < len(private_keys):
                        time.sleep(20)
                        
        elif choice == "2":
            private_keys = load_private_keys()
            if not private_keys:
                log_error("No private keys found in pk.txt")
                continue
            
            try:
                iterations = int(input(f"{Fore.CYAN}Enter number of chat iterations per cycle: {Style.RESET_ALL}").strip())
            except ValueError:
                log_warning("Invalid input. Using default value of 1")
                iterations = 1
            
            use_threads = input(f"{Fore.CYAN}Use multi-threading? (yes/no): {Style.RESET_ALL}").strip().lower() in ['y', 'yes']
            
            if use_threads:
                max_workers = min(5, len(private_keys))
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for private_key in private_keys:
                        futures.append(executor.submit(process_chat_continuous, private_key, iterations))
                    
                    try:
                        concurrent.futures.wait(futures)
                    except KeyboardInterrupt:
                        log_warning("Stopping all chat processes...")
                        executor.shutdown(wait=False)
            else:
                for private_key in private_keys:
                    process_chat_continuous(private_key, iterations)
            
        elif choice == "3":
            capsolver_key = input(f"{Fore.CYAN}Enter your Capsolver API key: {Style.RESET_ALL}").strip()
            if not capsolver_key:
                log_error("Capsolver API key is required")
                continue
            
            private_keys = load_private_keys()
            if not private_keys:
                log_error("No private keys found in pk.txt")
                continue
                
            success_count = process_faucet_claims(private_keys, capsolver_key)
            log_success(f"Completed faucet claims. Success: {success_count}/{len(private_keys)}")
            
        elif choice == "4":
            log_info("Exiting program...")
            break
            
        else:
            log_error("Invalid choice. Please try again.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        log_info("Program interrupted by user. Exiting...")
        sys.exit(0)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        sys.exit(1)
