from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import re
import time
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

VALID_API_KEY = "PETRO"

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        start_time = time.time()
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        api_key = query_params.get('key', [None])[0]
        username = query_params.get('username', [None])[0]

        self.process_request(api_key, username, start_time)

    def do_POST(self):
        start_time = time.time()
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        api_key = query_params.get('key', [None])[0]
        username = query_params.get('username', [None])[0]

        if not username or not api_key:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            try:
                body = json.loads(post_data.decode('utf-8'))
                if not api_key:
                    api_key = body.get('key')
                if not username:
                    username = body.get('username')
            except Exception:
                pass

        self.process_request(api_key, username, start_time)

    def process_request(self, api_key, username, start_time):
        if not api_key or api_key != VALID_API_KEY:
            self._send_json(
                401, 
                success=False, 
                error_message="Invalid or missing API key. Access denied.",
                start_time=start_time
            )
            return

        if not username:
            self._send_json(
                400, 
                success=False, 
                error_message="Username parameter is required. Usage: /api?key=PETRO&username=zuck",
                start_time=start_time
            )
            return

        try:
            profile_url = f"https://www.facebook.com/{username}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }

            response = requests.get(profile_url, headers=headers, timeout=2.0)
            
            name = None
            user_id = None
            profile_pic = None
            description = None
            followers = None
            likes = None
            
            if response.status_code == 200:
                raw_text = response.text
                
                og_title = re.search(r'<meta property="og:title" content="([^"]+)"', raw_text)
                if og_title:
                    name = og_title.group(1).replace(" | Facebook", "").strip()
                    
                og_image = re.search(r'<meta property="og:image" content="([^"]+)"', raw_text)
                if og_image:
                    profile_pic = og_image.group(1)
                    
                og_desc = re.search(r'<meta property="og:description" content="([^"]+)"', raw_text)
                if og_desc:
                    description = og_desc.group(1).strip()

                id_match = re.search(r'"page_id":"(\d+)"', raw_text) or re.search(r'"userID":"(\d+)"', raw_text) or re.search(r'entity_id":"(\d+)"', raw_text) or re.search(r'profile_id["\s:]+(\d+)', raw_text)
                if id_match:
                    user_id = id_match.group(1)

                followers_match = re.search(r'([\d.,]+[KkMmBb]?)\s*(?:followers|subscribers)', raw_text, re.IGNORECASE)
                if followers_match:
                    followers = followers_match.group(1)

                likes_match = re.search(r'([\d.,]+[KkMmBb]?)\s*likes', raw_text, re.IGNORECASE)
                if likes_match:
                    likes = likes_match.group(1)
                    if not followers:
                        followers = likes

            # Fast Public Sharer & oEmbed Hybrid Fallback for Restricted Pages
            if not name or "Log in" in name or name == "Facebook" or "log in or sign up" in str(description).lower():
                share_url = f"https://www.facebook.com/sharer/sharer.php?u={urllib.parse.quote(profile_url)}"
                share_resp = requests.get(share_url, headers=headers, timeout=1.8)
                if share_resp.status_code == 200:
                    share_text = share_resp.text
                    
                    s_title = re.search(r'<meta property="og:title" content="([^"]+)"', share_text)
                    if s_title:
                        clean_t = s_title.group(1).replace(" | Facebook", "").strip()
                        if clean_t and "Log in" not in clean_t:
                            name = clean_t

                    s_image = re.search(r'<meta property="og:image" content="([^"]+)"', share_text)
                    if s_image:
                        profile_pic = s_image.group(1)

                    s_desc = re.search(r'<meta property="og:description" content="([^"]+)"', share_text)
                    if s_desc:
                        description = s_desc.group(1).strip()

                if not name or "Log in" in name or name == "Facebook":
                    name = username.replace(".", " ").title()
                    description = f"Official public profile for {name} on Facebook."

            # Extract likes/followers from description if found in fallback
            if description:
                if not likes:
                    likes_match = re.search(r'([\d.,]+[KkMmBb]?)\s*likes', description, re.IGNORECASE)
                    if likes_match:
                        likes = likes_match.group(1)
                if not followers:
                    followers_match = re.search(r'([\d.,]+[KkMmBb]?)\s*(?:followers|subscribers)', description, re.IGNORECASE)
                    if followers_match:
                        followers = followers_match.group(1)
                    elif likes:
                        followers = likes

            if not user_id and profile_pic:
                media_id_match = re.search(r'media_id=(\d+)', profile_pic) or re.search(r'/v/t[\d.]+/(\d+)_', profile_pic)
                if media_id_match:
                    user_id = media_id_match.group(1)

            if not user_id:
                user_id = "Public_ID"

            found_emails = []
            found_phones = []

            if description:
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
                found_emails = list(set(re.findall(email_pattern, description)))
                found_phones = list(set(re.findall(phone_pattern, description)))

            result_data = {
                "user_id": user_id,
                "username_or_id": username,
                "name": name,
                "profile_picture": profile_pic,
                "profile_url": profile_url,
                "bio_description": description,
                "page_stats": {
                    "followers": followers,
                    "likes": likes
                },
                "extracted_contacts": {
                    "emails": found_emails if found_emails else None,
                    "phones": found_phones if found_phones else None
                }
            }

            self._send_json(200, success=True, payload=result_data, start_time=start_time)

        except Exception as e:
            self._send_json(500, success=False, error_message=str(e), start_time=start_time)

    def _send_json(self, status_code, success=True, payload=None, error_message=None, start_time=None):
        end_time = time.time()
        elapsed_ms = round((end_time - start_time) * 1000, 2) if start_time else 0
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        response_body = {
            "developer": "@fameneedsme",
            "responded_time": current_time,
            "execution_time": f"{elapsed_ms} ms",
            "success": success
        }

        if success and payload:
            response_body["data"] = payload
        elif error_message:
            response_body["error"] = error_message

        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(response_body, indent=2, ensure_ascii=False).encode('utf-8'))
