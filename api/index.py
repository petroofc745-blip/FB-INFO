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
                error_message="Username parameter is required. Usage: /api?key=PETRO&username=meta",
                start_time=start_time
            )
            return

        try:
            # Use mbasic.facebook.com to bypass standard Facebook server blocks
            target_url = f"https://mbasic.facebook.com/{username}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }

            session = requests.Session()
            response = session.get(target_url, headers=headers, timeout=10, allow_redirects=True)

            if response.status_code != 200:
                self._send_json(
                    400, 
                    success=False, 
                    error_message=f"Facebook blocked request with HTTP status {response.status_code}",
                    start_time=start_time
                )
                return

            html_text = response.text
            soup = BeautifulSoup(html_text, 'html.parser')

            # OpenGraph and Meta Extractors
            og_title = soup.find("meta", property="og:title") or soup.find("title")
            og_image = soup.find("meta", property="og:image")
            og_url = soup.find("meta", property="og:url")
            og_description = soup.find("meta", property="og:description")
            og_type = soup.find("meta", property="og:type")
            locale = soup.find("meta", property="og:locale")

            name = og_title["content"] if og_title and og_title.has_attr("content") else (og_title.string if og_title else None)
            profile_pic = og_image["content"] if og_image and og_image.has_attr("content") else None
            profile_url = og_url["content"] if og_url and og_url.has_attr("content") else f"https://www.facebook.com/{username}"
            description = og_description["content"] if og_description and og_description.has_attr("content") else None
            page_type = og_type["content"] if og_type and og_type.has_attr("content") else None
            profile_locale = locale["content"] if locale and locale.has_attr("content") else None

            # Clean name formatting
            if name:
                name = name.replace(" | Facebook", "").replace(" - Home", "").strip()

            # Extract numeric user/page ID
            user_id = None
            id_match = re.search(r'"entity_id":"(\d+)"', html_text) or re.search(r'fb://profile/(\d+)', html_text) or re.search(r'page_id=(\d+)', html_text) or re.search(r'rid=(\d+)', html_text)
            if id_match:
                user_id = id_match.group(1)

            found_emails = []
            found_phones = []
            followers = None
            likes = None

            if description:
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'

                found_emails = list(set(re.findall(email_pattern, description)))
                found_phones = list(set(re.findall(phone_pattern, description)))

                followers_match = re.search(r'([\d.,]+[KkMmBb]?)\s*followers', description, re.IGNORECASE)
                if followers_match:
                    followers = followers_match.group(1)

                likes_match = re.search(r'([\d.,]+[KkMmBb]?)\s*likes', description, re.IGNORECASE)
                if likes_match:
                    likes = likes_match.group(1)

            # Check if login wall blocked extraction completely
            if not name and not profile_pic:
                self._send_json(
                    404, 
                    success=False, 
                    error_message="Profile data restricted or blocked by Facebook login wall.",
                    start_time=start_time
                )
                return

            result_data = {
                "user_id": user_id,
                "username_or_id": username,
                "name": name,
                "profile_picture": profile_pic,
                "profile_url": profile_url,
                "type": page_type,
                "locale": profile_locale,
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
