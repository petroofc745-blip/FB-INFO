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
            
            # Using standard desktop browser headers that safely bypass login wall blocks for public profiles/pages
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Cache-Control": "max-age=0",
                "Sec-Ch-Ua": "\"Chromium\";v=\"122\", \"Not(A:Brand\";v=\"24\", \"Google Chrome\";v=\"122\"",
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": "\"Windows\"",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }

            name = None
            user_id = None
            profile_pic = None
            description = None

            # Fetch the public web page directly
            try:
                raw_response = requests.get(profile_url, headers=headers, timeout=3.0, allow_redirects=True)
                if raw_response.status_code == 200:
                    raw_text = raw_response.text
                    
                    # Extract Name from OpenGraph title
                    og_title = re.search(r'<meta property="og:title" content="([^"]+)"', raw_text)
                    if og_title:
                        t = og_title.group(1).replace(" | Facebook", "").strip()
                        if "Log into Facebook" not in t:
                            name = t

                    # Extract Profile Picture from OpenGraph image
                    og_img = re.search(r'<meta property="og:image" content="([^"]+)"', raw_text)
                    if og_img:
                        profile_pic = og_img.group(1)
                        media_id_match = re.search(r'media_id=(\d+)', profile_pic)
                        if media_id_match:
                            user_id = media_id_match.group(1)

                    # Extract Bio / Description from OpenGraph description
                    og_desc = re.search(r'<meta property="og:description" content="([^"]+)"', raw_text)
                    if og_desc:
                        d = og_desc.group(1)
                        if "Log into Facebook" not in d:
                            description = d

                    # Deep search fallback patterns for internal IDs & numeric Profile IDs
                    if not user_id:
                        id_patterns = [
                            r'"entity_id":"(\d+)"',
                            r'"page_id":"(\d+)"',
                            r'profile_id=(\d+)',
                            r'"ownerId":"(\d+)"',
                            r'"userID":"(\d+)"',
                            r'fb://profile/(\d+)'
                        ]
                        for pattern in id_patterns:
                            m = re.search(pattern, raw_text)
                            if m:
                                user_id = m.group(1)
                                break
            except Exception:
                pass

            # Fallback to oEmbed endpoint if main page scrape missed details
            if not description or not name or not user_id:
                try:
                    oembed_url = f"https://www.facebook.com/plugins/page/oembed.json?url={urllib.parse.quote(profile_url, safe='')}"
                    oembed_resp = requests.get(oembed_url, headers=headers, timeout=2.0, allow_redirects=True)
                    if oembed_resp.status_code == 200:
                        data = oembed_resp.json()
                        if not name:
                            name = data.get("title")
                        html_snippet = data.get("html", "")
                        soup = BeautifulSoup(html_snippet, 'html.parser')
                        block_quote = soup.find("blockquote")
                        if block_quote and not description:
                            description = block_quote.get_text(strip=True)
                        if not user_id:
                            id_match = re.search(r'id=(\d+)', html_snippet) or re.search(r'page_id=(\d+)', html_snippet)
                            if id_match:
                                user_id = id_match.group(1)
                except Exception:
                    pass

            # Fallback construct profile image via crawler if user_id is found
            if user_id and not profile_pic:
                profile_pic = f"https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id={user_id}"

            if not name or "Log into Facebook" in name:
                name = username.capitalize()

            if description and "Log into Facebook" in description:
                description = None

            followers = None
            likes = None

            if description:
                followers_match = re.search(r'([\d.,]+[KkMmBb]?)\s*(?:followers|subscribers)', description, re.IGNORECASE)
                if followers_match:
                    followers = followers_match.group(1)
                else:
                    likes_match = re.search(r'([\d.,]+[KkMmBb]?)\s*likes', description, re.IGNORECASE)
                    if likes_match:
                        likes = likes_match.group(1)
                        followers = likes

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
