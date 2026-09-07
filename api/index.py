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
            oembed_url = f"https://www.facebook.com/plugins/page/oembed.json?url={profile_url}"
            
            headers = {
                "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "application/json,text/html,*/*"
            }

            # Fast single oEmbed fetch
            response = requests.get(oembed_url, headers=headers, timeout=4)
            
            name = None
            user_id = None
            profile_pic = None
            description = None
            
            if response.status_code == 200:
                data = response.json()
                name = data.get("title")
                html_snippet = data.get("html", "")
                
                soup = BeautifulSoup(html_snippet, 'html.parser')
                block_quote = soup.find("blockquote")
                if block_quote:
                    description = block_quote.get_text(strip=True)
                
                # Extract User/Page ID from SDK URL or data attributes
                id_match = re.search(r'id=(\d+)', html_snippet) or re.search(r'page_id=(\d+)', html_snippet) or re.search(r'href="https://www.facebook.com/(\d+)"', html_snippet)
                if id_match:
                    user_id = id_match.group(1)

            # Fast parallel metadata check if oEmbed misses image/ID
            if not profile_pic or not user_id:
                raw_response = requests.get(profile_url, headers=headers, timeout=4)
                if raw_response.status_code == 200:
                    raw_text = raw_response.text
                    
                    # Extract profile picture from og:image
                    og_image_match = re.search(r'<meta property="og:image" content="([^"]+)"', raw_text)
                    if og_image_match:
                        profile_pic = og_image_match.group(1)
                        # Extract user ID directly from lookaside media query parameter if available (e.g., media_id=4)
                        media_id_match = re.search(r'media_id=(\d+)', profile_pic)
                        if media_id_match and not user_id:
                            user_id = media_id_match.group(1)

                    if not name:
                        og_title_match = re.search(r'<meta property="og:title" content="([^"]+)"', raw_text)
                        if og_title_match:
                            name = og_title_match.group(1).replace(" | Facebook", "")

                    if not description:
                        og_desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', raw_text)
                        if og_desc_match:
                            description = og_desc_match.group(1)

            # Fallback user ID extraction via graph/profile patterns if still missing
            if not user_id:
                profile_id_match = re.search(r'"entity_id":"(\d+)"', response.text if 'response' in locals() else "")
                if profile_id_match:
                    user_id = profile_id_match.group(1)

            if not name or "Facebook - log in" in name or name == "Facebook":
                self._send_json(
                    404, 
                    success=False, 
                    error_message="Profile data is private or restricted by Facebook login constraints.",
                    start_time=start_time
                )
                return

            found_emails = []
            found_phones = []
            followers = None
            likes = None

            if description:
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                phone_pattern = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'

                found_emails = list(set(re.findall(email_pattern, description)))
                found_phones = list(set(re.findall(phone_pattern, description)))

                # Flexible followers and likes matching
                followers_match = re.search(r'([\d.,]+[KkMmBb]?)\s*(?:followers|subscribers)', description, re.IGNORECASE)
                if followers_match:
                    followers = followers_match.group(1)
                else:
                    # If page shows likes instead of followers, duplicate likes value into followers for compatibility if needed
                    likes_match = re.search(r'([\d.,]+[KkMmBb]?)\s*likes', description, re.IGNORECASE)
                    if likes_match:
                        likes = likes_match.group(1)
                        followers = likes  # Map likes to followers if explicit follower count string is missing on legacy pages

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
