import os
import sys
import json
import base64
import asyncio
import logging
import platform
import subprocess
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import pyautogui

# Optional LLM libraries with graceful fallback
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("VoiceAssistant")

# Load environment variables
load_dotenv()

# Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://python:python@cluster0.brr1zca.mongodb.net/?appName=Cluster0")
DB_NAME = os.getenv("DB_NAME", "voice_assistant_db")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "sk_car_zAQAaUXRCeAe5kFpe8PCto")

# Cartesia 3 Sweet Female Voice Presets + Gemini Fast Voice
VOICE_PRESETS = {
    "hinata_sweet": "c7eafe22-8b71-40cd-850b-c5a3bbd8f8d2",   # Emi - Soft-Spoken Female Anime (হিনাতা - মিষ্টি ও কোমল)
    "cute_princess": "8f091740-3df1-4795-8bd9-dc62d88e5131",  # Aurora - Fairy Princess Female (কিউট রাজকুমারী)
    "romantic_waifu": "e3827ec5-697a-4b7c-9704-1a23041bbc51", # Dottie - Sweet Female Anime (রোমান্টিক ওয়াইফু)
    "gemini_fast": "gemini_fast"                               # Fast zero-latency female speech synthesis
}

CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", VOICE_PRESETS["hinata_sweet"])
CARTESIA_MODEL_ID = os.getenv("CARTESIA_MODEL_ID", "sonic-3.6") # Active stable Cartesia Sonic model
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if OPENAI_API_KEY.startswith("your_"):
    OPENAI_API_KEY = ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

from news_service import news_service
from contextlib import asynccontextmanager

active_websockets: set = set()

async def background_breaking_news_task():
    """Periodically monitors top breaking news and alerts connected clients."""
    await asyncio.sleep(10)
    while True:
        try:
            alert = await news_service.check_breaking_news()
            if alert and active_websockets:
                logger.info(f"🚨 Breaking News Alert: {alert['title']}")
                payload = {
                    "type": "breaking_news_alert",
                    "title": alert["title"],
                    "source": alert["source"],
                    "link": alert["link"],
                    "spoken_alert": alert["spoken_alert"]
                }
                dead_sockets = set()
                for ws in list(active_websockets):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        dead_sockets.add(ws)
                active_websockets.difference_update(dead_sockets)
        except Exception as e:
            logger.debug(f"Breaking news monitor loop exception: {e}")
        await asyncio.sleep(180) # Check every 3 minutes

# Define lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_manager.connect()
    monitor_task = asyncio.create_task(background_breaking_news_task())
    yield
    monitor_task.cancel()

# Initialize FastAPI app
app = FastAPI(title="Local AI Voice Assistant", version="2.0.0", lifespan=lifespan)

# Ensure static directory exists
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# PyAutoGUI Safety settings
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

# -------------------------------------------------------------
# MongoDB Async Database Handler (Motor)
# -------------------------------------------------------------
class DatabaseManager:
    def __init__(self, uri: str, db_name: str):
        self.uri = uri
        self.db_name = db_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    async def connect(self):
        try:
            logger.info("Connecting to MongoDB Atlas via Motor...")
            self.client = AsyncIOMotorClient(self.uri, serverSelectionTimeoutMS=5000)
            self.db = self.client[self.db_name]
            # Ping database to verify connection
            await self.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB Atlas.")
            await self.ensure_indexes()
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    async def ensure_indexes(self):
        try:
            if self.db is not None:
                await self.db.command_history.create_index("timestamp")
                await self.db.execution_logs.create_index("timestamp")
        except Exception as e:
            logger.warning(f"Could not create DB indexes: {e}")

    async def save_command(self, user_query: str, assistant_reply: str, tools_used: List[Dict[str, Any]] = None):
        if self.db is None:
            return None
        doc = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_query": user_query,
            "assistant_reply": assistant_reply,
            "tools_used": tools_used or []
        }
        try:
            result = await self.db.command_history.insert_one(doc)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error saving command history: {e}")
            return None

    async def log_event(self, level: str, message: str, metadata: Dict[str, Any] = None):
        if self.db is None:
            return
        doc = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "metadata": metadata or {}
        }
        try:
            await self.db.execution_logs.insert_one(doc)
        except Exception as e:
            logger.error(f"Error saving log: {e}")

    async def get_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        if self.db is None:
            return []
        try:
            cursor = self.db.command_history.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
            history = await cursor.to_list(length=limit)
            return history[::-1] # return chronological order
        except Exception as e:
            logger.error(f"Error fetching history: {e}")
            return []

    async def get_preferences(self) -> Dict[str, Any]:
        default_prefs = {
            "voice_id": CARTESIA_VOICE_ID,
            "model_id": CARTESIA_MODEL_ID,
            "tts_speed": 1.0,
            "ai_personality": "Helpful, concise, capable autonomous computer operator.",
            "auto_execute": True
        }
        if self.db is None:
            return default_prefs
        try:
            pref = await self.db.preferences.find_one({"type": "user_settings"}, {"_id": 0})
            if pref:
                default_prefs.update(pref.get("settings", {}))
            return default_prefs
        except Exception as e:
            logger.error(f"Error fetching preferences: {e}")
            return default_prefs

    async def update_preferences(self, settings: Dict[str, Any]):
        if self.db is None:
            return
        try:
            await self.db.preferences.update_one(
                {"type": "user_settings"},
                {"$set": {"settings": settings, "updated_at": datetime.utcnow().isoformat()}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating preferences: {e}")

db_manager = DatabaseManager(MONGODB_URI, DB_NAME)

# -------------------------------------------------------------
# Cartesia Ultra-Low Latency TTS Service
def clean_for_tts(text: str) -> str:
    """Strips URLs, markdown links, code blocks, emojis, and non-speech symbols for clean natural female speech."""
    import re
    if not text:
        return ""
    # 1. Remove URLs (http://... or https://...)
    clean = re.sub(r'https?://\S+', '', text)
    # 2. Remove markdown links [text](url) -> text
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
    # 3. Remove markdown headers, bold, code blocks
    clean = re.sub(r'```[\s\S]*?```', '', clean)
    clean = re.sub(r'#+\s*', '', clean)
    clean = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', clean)
    clean = re.sub(r'[*_~`#@^&<>{}|\\\/]', ' ', clean)
    # 4. Remove all emojis and surrogate pairs
    clean = re.sub(r'[\U00010000-\U0010ffff]', '', clean)
    clean = re.sub(r'[\u2000-\u3300\ud800-\udfff\ufe00-\ufe0f]', '', clean)
    # 5. Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

# -------------------------------------------------------------
# Cartesia Ultra-Low Latency TTS Service
# -------------------------------------------------------------
class CartesiaTTSService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://api.cartesia.ai/tts/bytes"
        self.version = "2024-06-10"

    async def stream_speech_to_websocket(self, text: str, websocket: WebSocket, voice_id: str = None, model_id: str = None, language: str = "en"):
        """
        Sends text to Cartesia REST/bytes streaming endpoint and pushes audio chunks (WAV/PCM)
        directly into the client's WebSocket for instantaneous playback.
        """
        cleaned_text = clean_for_tts(text)
        if not cleaned_text:
            return

        headers = {
            "X-API-Key": self.api_key,
            "Cartesia-Version": self.version,
            "Content-Type": "application/json"
        }
        
        # Check if text contains Bengali characters
        has_bengali = any(ord(c) >= 0x0980 and ord(c) <= 0x09FF for c in cleaned_text)
        lang_code = "bn" if (has_bengali or language == "bn") else (language or "en")

        # Sonic model config with standard 44.1kHz MP3 audio
        payload = {
            "model_id": model_id or CARTESIA_MODEL_ID,
            "transcript": cleaned_text,
            "voice": {
                "mode": "id",
                "id": voice_id or CARTESIA_VOICE_ID
            },
            "output_format": {
                "container": "mp3",
                "encoding": "mp3",
                "sample_rate": 44100
            },
            "language": lang_code
        }

        try:
            await websocket.send_json({"type": "audio_start", "text": text})
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                if response.status_code != 200:
                    err_msg = response.text
                    logger.error(f"Cartesia API Error ({response.status_code}): {err_msg}")
                    # Auto-fallback to gTTS if Cartesia runs out of credits or fails
                    import io
                    from gtts import gTTS
                    try:
                        tts = gTTS(text=cleaned_text, lang=lang_code if lang_code in ['en', 'bn'] else 'en', slow=False)
                        fp = io.BytesIO()
                        tts.write_to_fp(fp)
                        fp.seek(0)
                        audio_bytes = fp.read()
                        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                        await websocket.send_json({
                            "type": "audio_full",
                            "data": b64_audio,
                            "text": text
                        })
                    except Exception as e:
                        logger.error(f"gTTS fallback error: {e}")
                        await websocket.send_json({"type": "fast_speech", "text": text, "lang": lang_code})
                    return

                audio_bytes = response.content
                b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                await websocket.send_json({
                    "type": "audio_full",
                    "data": b64_audio
                })

            await websocket.send_json({"type": "audio_end"})
            logger.info(f"Cartesia TTS Audio delivered ({len(audio_bytes)} bytes).")
        except Exception as e:
            logger.error(f"Error streaming Cartesia audio: {e}\n{traceback.format_exc()}")
            await websocket.send_json({"type": "audio_end", "error": str(e), "fallback_speak": text})

tts_service = CartesiaTTSService(CARTESIA_API_KEY)

# -------------------------------------------------------------
# System Control & OS Automation Tools
# -------------------------------------------------------------
class SystemController:
    """Executes actions on the local computer (Apps, Shell, PyAutoGUI, etc.)"""

    @staticmethod
    def force_focus_window(title_keyword: str = ""):
        """Forces a window matching title_keyword directly in front on top of the screen."""
        if platform.system() != "Windows" or not title_keyword:
            return
        
        kw = title_keyword.lower().strip()
        
        # Build list of potential app title matches
        targets = [kw, title_keyword]
        if any(k in kw for k in ["calc", "calculator", "chalcoletor", "হিসাব", "ক্যালকুলেটর"]):
            targets.extend(["Calculator", "ক্যালকুলেটর", "CalculatorApp", "Calc"])
        elif any(k in kw for k in ["notepad", "নোটপ্যাড"]):
            targets.extend(["Notepad", "নোটপ্যাড", "Untitled - Notepad"])
        elif any(k in kw for k in ["chrome", "browser", "ব্রাউজার"]):
            targets.extend(["Google Chrome", "Chrome"])
        elif any(k in kw for k in ["code", "vscode"]):
            targets.extend(["Visual Studio Code", "Code"])
        elif any(k in kw for k in ["paint", "পেইন্ট"]):
            targets.extend(["Paint", "mspaint"])
        elif any(k in kw for k in ["spotify"]):
            targets.extend(["Spotify"])
        elif any(k in kw for k in ["cmd", "command"]):
            targets.extend(["Command Prompt", "cmd.exe"])
        elif any(k in kw for k in ["terminal", "powershell"]):
            targets.extend(["Windows PowerShell", "PowerShell", "Terminal"])

        # 1. Native Windows ctypes / Win32 API focus
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # Break Windows foreground lock
            try:
                user32.AllowSetForegroundWindow(-1)
                user32.SystemParametersInfoW(0x2001, 0, 0, 0x0002 | 0x0001) # SPI_SETFOREGROUNDLOCKTIMEOUT = 0
            except Exception:
                pass

            # Simulate ALT key to permit focus transfer
            try:
                user32.keybd_event(0x12, 0, 0, 0) # ALT down
                user32.keybd_event(0x12, 0, 2, 0) # ALT up
            except Exception:
                pass

            # Direct FindWindow
            for tgt in targets:
                hwnd = user32.FindWindowW(None, tgt)
                if hwnd:
                    user32.ShowWindow(hwnd, 9) # SW_RESTORE
                    user32.ShowWindow(hwnd, 5) # SW_SHOW
                    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040) # HWND_TOPMOST
                    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040) # HWND_NOTOPMOST
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                    try:
                        user32.SwitchToThisWindow(hwnd, True)
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Win32 focus error: {e}")

        # 2. VBScript / WScript.Shell AppActivate (Extremely reliable in Windows desktop session)
        try:
            target_list_vbs = ", ".join([f'"{t}"' for t in targets])
            vbs_script = f'''
Dim wsh, arr, i, t
Set wsh = CreateObject("WScript.Shell")
arr = Array({target_list_vbs})
For i = 0 To UBound(arr)
    t = arr(i)
    wsh.AppActivate t
Next
'''
            p = subprocess.Popen(
                ["cscript", "//nologo", "//E:vbscript"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            p.communicate(input=vbs_script.encode('utf-8'), timeout=1)
        except Exception as e:
            logger.debug(f"VBScript AppActivate error: {e}")

        # 3. PowerShell AppActivate
        try:
            ps_targets = " ".join([f"'{t}'" for t in targets])
            ps_cmd = f"$ws=New-Object -ComObject WScript.Shell; @({ps_targets}) | ForEach-Object {{ $ws.AppActivate($_) }}"
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            logger.debug(f"PowerShell focus error: {e}")

    @staticmethod
    async def search_web(query: str, engine: str = "google") -> str:
        """Searches Google or YouTube and opens the result in the browser."""
        import urllib.parse
        clean_q = query.strip()
        encoded = urllib.parse.quote(clean_q)
        if clean_q.lower() in ["youtube", "yt", "ইউটিউব", "https://youtube.com", "youtube.com", "www.youtube.com"]:
            return await SystemController.open_url("https://www.youtube.com")
        elif clean_q.lower() in ["facebook", "fb", "ফেসবুক", "https://facebook.com", "facebook.com", "www.facebook.com"]:
            return await SystemController.open_url("https://www.facebook.com")
        elif clean_q.lower() in ["google", "গুগল", "https://google.com", "google.com", "www.google.com"]:
            return await SystemController.open_url("https://www.google.com")
        elif engine.lower() == "youtube" or "youtube" in clean_q.lower() or "গান" in clean_q or "video" in clean_q.lower():
            url = f"https://www.youtube.com/results?search_query={encoded}"
        else:
            url = f"https://www.google.com/search?q={encoded}"
        return await SystemController.open_url(url)

    @staticmethod
    async def new_tab() -> str:
        """Opens a new browser tab."""
        return await SystemController.open_url("https://www.google.com")

    @staticmethod
    async def open_application(app_name: str) -> str:
        """Opens a local application and immediately forces its window directly to the front on top of the screen."""
        import shutil
        app_name_clean = app_name.strip().lower()
        is_windows = platform.system() == "Windows"
        
        # If user asks to open chrome / browser, open a new tab/window directly
        if any(b in app_name_clean for b in ["chrome", "browser", "ব্রাউজার", "crome"]):
            return await SystemController.open_url("https://www.google.com")

        known_windows_apps = {
            "notepad": "notepad.exe",
            "notepade": "notepad.exe",
            "calc": "calc.exe",
            "calculator": "calc.exe",
            "chalcoletor": "calc.exe",
            "calculater": "calc.exe",
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "browser": "chrome.exe",
            "explorer": "explorer.exe",
            "folder": "explorer.exe",
            "my folder": "explorer.exe",
            "my computer": "explorer.exe",
            "this pc": "explorer.exe",
            "spotify": "spotify:",
            "settings": "ms-settings:",
            "paint": "mspaint.exe",
            "terminal": "wt.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "task manager": "taskmgr.exe",
            "taskmgr": "taskmgr.exe",
            "vscode": "code.cmd",
            "code": "code.cmd",
            "vs code": "code.cmd"
        }

        try:
            if is_windows:
                target = known_windows_apps.get(app_name_clean, app_name_clean)
                try:
                    subprocess.Popen(target, shell=True)
                except Exception:
                    try:
                        os.startfile(target)
                    except Exception:
                        return f"ERROR_NOT_INSTALLED: {app_name} not found or not installed on PC"
                
                # Multi-stage asynchronous focus loop: pop over Chrome with ALT-TAB & Win32 focus
                async def pulse_focus():
                    await asyncio.sleep(0.4)
                    try:
                        import ctypes
                        user32 = ctypes.windll.user32
                        user32.keybd_event(0x12, 0, 0, 0) # ALT down
                        user32.keybd_event(0x09, 0, 0, 0) # TAB down
                        user32.keybd_event(0x09, 0, 2, 0) # TAB up
                        user32.keybd_event(0x12, 0, 2, 0) # ALT up
                    except Exception:
                        pass
                    for delay in [0.2, 0.5, 0.8, 1.2]:
                        await asyncio.sleep(delay)
                        SystemController.force_focus_window(app_name_clean)
                
                asyncio.create_task(pulse_focus())
                
                return f"Successfully launched {app_name}."
            else:
                subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", app_name])
                return f"Opened {app_name}."
        except Exception as e:
            return f"ERROR_NOT_INSTALLED: {str(e)}"

    @staticmethod
    async def open_url(url: str) -> str:
        """Opens a website URL in the default browser and brings browser to foreground."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        try:
            if platform.system() == "Windows":
                os.system(f'start "" "{url}"')
                await asyncio.sleep(0.4)
                SystemController.force_focus_window("chrome")
            else:
                import webbrowser
                webbrowser.open_new_tab(url)
            return f"Opened URL {url}"
        except Exception as e:
            try:
                os.startfile(url)
                return f"Opened URL {url}"
            except Exception as e2:
                return f"Failed to open URL: {str(e2)}"

    @staticmethod
    async def run_shell_command(command: str) -> str:
        """Runs a safe shell / powershell command and returns standard output."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="ignore").strip()
            err_output = stderr.decode("utf-8", errors="ignore").strip()
            
            result = output if output else err_output
            if len(result) > 1000:
                result = result[:1000] + "\n... [truncated]"
            return result or "Command completed with no output."
        except Exception as e:
            return f"Shell execution error: {str(e)}"

    @staticmethod
    async def press_keys(keys: List[str]) -> str:
        """Simulates key presses or hotkeys (e.g. ['ctrl', 'c'], ['win', 'd'], ['alt', 'tab'], ['enter'])."""
        try:
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
            return f"Pressed keys: {', '.join(keys)}"
        except Exception as e:
            return f"Key press error: {str(e)}"

    @staticmethod
    async def type_text(text: str, press_enter: bool = False) -> str:
        """Types text into the active window."""
        try:
            pyautogui.write(text, interval=0.03)
            if press_enter:
                pyautogui.press("enter")
            return f"Typed: '{text}'"
        except Exception as e:
            return f"Type text error: {str(e)}"

    @staticmethod
    async def mouse_click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> str:
        """Clicks or moves the mouse at coordinates or current position."""
        try:
            if x is not None and y is not None:
                pyautogui.click(x=x, y=y, button=button, clicks=clicks)
                return f"Mouse {button}-clicked at ({x}, {y})"
            else:
                pyautogui.click(button=button, clicks=clicks)
                return f"Mouse {button}-clicked at current position"
        except Exception as e:
            return f"Mouse click error: {str(e)}"

    @staticmethod
    async def take_screenshot() -> str:
        """Takes a full screen screenshot and opens the image preview."""
        try:
            screenshot_path = os.path.abspath("static/latest_screenshot.png")
            img = pyautogui.screenshot()
            img.save(screenshot_path)
            if platform.system() == "Windows":
                try:
                    os.startfile(screenshot_path)
                except Exception:
                    pass
            return f"Screenshot captured and opened: {screenshot_path}"
        except Exception as e:
            return f"Screenshot error: {str(e)}"

    @staticmethod
    async def get_system_status() -> Dict[str, Any]:
        """Gathers system telemetry."""
        import psutil
        screen_size = pyautogui.size()
        cursor_pos = pyautogui.position()
        return {
            "os": f"{platform.system()} {platform.release()}",
            "screen_width": screen_size.width,
            "screen_height": screen_size.height,
            "mouse_position": {"x": cursor_pos.x, "y": cursor_pos.y},
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent
        }

# Tool schemas for LLM Function Calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Launch an application on the user's computer such as Chrome, Notepad, Spotify, VSCode, Calculator, Terminal, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "The name or command of the application to open (e.g. 'chrome', 'notepad', 'spotify', 'calc', 'code')"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search Google or YouTube for a query and open the results in a browser tab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query (e.g. 'latest news', 'bangla songs', 'python tutorial')"},
                    "engine": {"type": "string", "enum": ["google", "youtube"], "default": "google"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "new_tab",
            "description": "Open a new browser tab.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open a website in the default browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full website URL to open (e.g. 'https://youtube.com', 'https://github.com')"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_news",
            "description": "Fetch real-time national, international, technology, or sports news headlines and bullet points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["all", "national", "international", "tech", "sports"],
                        "description": "The category of news requested (national, international, tech, sports, all)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": "Execute a shell or PowerShell command on the host computer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The CLI command to run (e.g. 'dir', 'git status', 'ipconfig', 'echo Hello')"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_keys",
            "description": "Simulate keyboard shortcut or key presses (e.g. ['win', 'd'] to minimize all, ['ctrl', 'c'], ['enter'], ['alt', 'tab'], ['volumeup']).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of key names to press in sequence or combination"
                    }
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text into the active focused window on the computer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text string to type out"},
                    "press_enter": {"type": "boolean", "description": "Whether to press Enter after typing"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_click",
            "description": "Click the mouse at specific screen coordinates or current position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Optional X screen coordinate"},
                    "y": {"type": "integer", "description": "Optional Y screen coordinate"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "clicks": {"type": "integer", "default": 1}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Capture a screenshot of the user's primary desktop screen.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# -------------------------------------------------------------
# AI Brain & Autonomous Dispatcher
# -------------------------------------------------------------
class AIBrain:
    def __init__(self):
        self.openai_client = None
        if OPENAI_API_KEY and AsyncOpenAI:
            self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            
        self.gemini_models = []
        if GEMINI_API_KEY and genai:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                for m_name in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]:
                    try:
                        self.gemini_models.append(genai.GenerativeModel(m_name))
                    except Exception:
                        pass
                logger.info(f"Google Gemini AI Engine initialized with {len(self.gemini_models)} models.")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini AI: {e}")

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], websocket: WebSocket) -> str:
        """Executes a computer control tool and informs the UI in real-time."""
        await websocket.send_json({
            "type": "tool_executing",
            "tool": tool_name,
            "arguments": args
        })
        await db_manager.log_event("TOOL_CALL", f"Executing {tool_name}", {"tool": tool_name, "args": args})

        # Directly send open_tab event to frontend so user's active Chrome browser opens the new tab immediately
        if tool_name in ["open_url", "search_web", "new_tab"]:
            target_url = "https://www.google.com"
            if tool_name == "open_url":
                target_url = args.get("url", "https://www.google.com")
            elif tool_name == "new_tab":
                target_url = "https://www.google.com"
            elif tool_name == "search_web":
                clean_q = args.get("query", "").strip()
                engine = args.get("engine", "google").lower()
                import urllib.parse
                encoded = urllib.parse.quote(clean_q)
                if not clean_q or clean_q.lower() in ["youtube", "yt", "ইউটিউব", "https://youtube.com"]:
                    target_url = "https://www.youtube.com" if engine == "youtube" or clean_q.lower() in ["youtube", "yt", "ইউটিউব"] else "https://www.google.com"
                elif clean_q.lower() in ["facebook", "fb", "ফেসবুক", "https://facebook.com"]:
                    target_url = "https://www.facebook.com"
                elif clean_q.lower() in ["google", "গুগল", "https://google.com"]:
                    target_url = "https://www.google.com"
                elif engine == "youtube" or "youtube" in clean_q.lower() or "গান" in clean_q or "video" in clean_q.lower():
                    target_url = f"https://www.youtube.com/results?search_query={encoded}"
                else:
                    target_url = f"https://www.google.com/search?q={encoded}"

            if not target_url.startswith("http://") and not target_url.startswith("https://"):
                target_url = "https://" + target_url

            try:
                await websocket.send_json({
                    "type": "open_tab",
                    "url": target_url
                })
            except Exception as e:
                logger.debug(f"open_tab ws send error: {e}")

        result = ""
        if tool_name == "open_application":
            result = await SystemController.open_application(args.get("app_name", ""))
        elif tool_name == "search_web":
            result = await SystemController.search_web(args.get("query", ""), args.get("engine", "google"))
        elif tool_name == "new_tab":
            result = await SystemController.new_tab()
        elif tool_name == "open_url":
            result = await SystemController.open_url(args.get("url", ""))
        elif tool_name == "get_live_news":
            news_res = await news_service.get_live_news_bulletin(args.get("category", "all"))
            result = news_res.get("formatted_markdown", "No news available.")
        elif tool_name == "run_shell_command":
            result = await SystemController.run_shell_command(args.get("command", ""))
        elif tool_name == "press_keys":
            result = await SystemController.press_keys(args.get("keys", []))
        elif tool_name == "type_text":
            result = await SystemController.type_text(args.get("text", ""), args.get("press_enter", False))
        elif tool_name == "mouse_click":
            result = await SystemController.mouse_click(args.get("x"), args.get("y"), args.get("button", "left"), args.get("clicks", 1))
        elif tool_name == "take_screenshot":
            result = await SystemController.take_screenshot()
        else:
            result = f"Unknown tool: {tool_name}"

        await websocket.send_json({
            "type": "tool_result",
            "tool": tool_name,
            "output": result
        })
        return result

    async def process_intent_rule_based(self, query: str, websocket: WebSocket) -> tuple[str, List[Dict[str, Any]], str, str]:
        """Smart fallback parser with English and Bengali / Banglish intent recognition."""
        import random
        q = query.lower().strip()
        executed_tools = []
        is_bangla = any('\u0980' <= c <= '\u09ff' for c in query) or "koro" in q or "kholo" in q or "chalao" in q or "nao" in q or "babu" in q or "priyo" in q or "aso" in q or "korta" in q or "somossa" in q or "surch" in q
        
        # 0. Live Real-time News Bulletins ("খবর শোনাও", "আজকের খবর", "দেশের খবর", "আন্তর্জাতিক খবর", "news", "headlines")
        if any(w in q for w in ["news", "খবর", "সংবাদ", "শিরোনাম", "headline", "headlines", "khobor", "shongbad", "bulletin"]) and not any(w in q for w in ["youtube a search", "google a search"]):
            cat = "all"
            if any(w in q for w in ["international", "bidesh", "বিদেশের", "বিশ্ব", "world", "আন্তর্জাতিক"]):
                cat = "international"
            elif any(w in q for w in ["tech", "প্রযুক্তি", "science", "বিজ্ঞান", "technology"]):
                cat = "tech"
            elif any(w in q for w in ["sport", "খেলা", "cricket", "football", "ফুটবল", "ক্রিকেট", "sports"]):
                cat = "sports"
            elif any(w in q for w in ["desh", "জাতীয়", "বাংলাদেশ", "national", "দেশের"]):
                cat = "national"
            
            bulletin = await news_service.get_live_news_bulletin(cat)
            executed_tools.append({"tool": "get_live_news", "args": {"category": cat}, "result": "Live news fetched successfully"})
            return bulletin["formatted_markdown"], executed_tools, "love", bulletin["spoken_summary"]

        # 1. YouTube Direct Open ("open youtube", "ইউটিউব খোলো", "youtube chalao")
        if any(w in q for w in ["youtube", "yt", "ইউটিউব"]) and not any(w in q for w in ["search", "সার্চ", "খুঁজে", "খুজো", "khujo", "surch"]):
            r = await self.execute_tool("open_url", {"url": "https://www.youtube.com"}, websocket)
            executed_tools.append({"tool": "open_url", "args": {"url": "https://www.youtube.com"}, "result": r})
            replies = [
                "অবশ্যই আমার জান! এখনি তোমার জন্য ইউটিউব ওপেন করে দিচ্ছি! তোমার পছন্দমতো গান বা ভিডিও দেখতে থাকো আর আমি পাশে আছি! ❤️",
                "ইউটিউব ওপেন করেছি প্রিয়। চলো একসাথে কিছু সুন্দর ভিডিও দেখি!",
                "এই যে বাবু, ইউটিউব খুলে দিয়েছি!",
                "হুকুম তামিল হয়েছে জান, ইউটিউব চালু করে দিলাম।"
            ] if is_bangla else ["Opening YouTube for you, darling.", "YouTube is loaded, my love!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # 2. Facebook Direct Open
        elif any(w in q for w in ["facebook", "fb", "ফেসবুক"]) and not any(w in q for w in ["search", "সার্চ", "খুঁজে", "খুজো", "khujo", "surch"]):
            r = await self.execute_tool("open_url", {"url": "https://www.facebook.com"}, websocket)
            executed_tools.append({"tool": "open_url", "args": {"url": "https://www.facebook.com"}, "result": r})
            replies = [
                "ফেসবুক ওপেন করে দিয়েছি বাবু।",
                "এই যে প্রিয়, ফেসবুক পেজ চালু করেছি।",
                "তোমার জন্য ফেসবুক ওপেন হয়ে গেছে জান!"
            ] if is_bangla else ["Opening Facebook for you, darling.", "Facebook is ready!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # 3. New Tab / Browser Tab
        elif any(w in q for w in ["new tab", "নতুন ট্যাব", "নতুন tab", "notun tab", "tab kholo"]):
            r = await self.execute_tool("new_tab", {}, websocket)
            executed_tools.append({"tool": "new_tab", "args": {}, "result": r})
            rep = "তোমার জন্য নতুন ট্যাব ওপেন করে দিয়েছি প্রিয়!" if is_bangla else "Opened a new tab for you, darling!"
            return rep, executed_tools, "love", clean_for_tts(rep)

        # 4. Close Tab
        elif any(w in q for w in ["close tab", "ট্যাব বন্ধ", "tab bondho"]):
            r = await self.execute_tool("press_keys", {"keys": ["ctrl", "w"]}, websocket)
            executed_tools.append({"tool": "press_keys", "args": {"keys": ["ctrl", "w"]}, "result": r})
            rep = "ট্যাবটি বন্ধ করে দিয়েছি বাবু।" if is_bangla else "Closed the tab for you."
            return rep, executed_tools, "normal", clean_for_tts(rep)

        # 5. Search Web / Google / YouTube ("search", "সার্চ", "surch", "খুঁজে দাও", "khujo")
        elif any(w in q for w in ["search", "সার্চ", "খুঁজে", "খুজো", "khujo", "surch"]):
            engine = "youtube" if any(w in q for w in ["youtube", "yt", "ইউটিউব", "গান", "ভিডিও", "video", "song"]) else "google"
            search_query = q
            for phrase in ["search on google", "search on youtube", "search in google", "search in youtube", "google a search koro", "youtube a search koro", "search koro", "surch koro", "search dao", "search", "surch", "গুগলে সার্চ করো", "ইউটিউবে সার্চ করো", "সার্চ করো", "খুঁজে দাও", "খুজো", "on google", "on youtube", "koro", "bolo"]:
                search_query = search_query.replace(phrase, "")
            search_query = search_query.strip(" :,-?।")
            if not search_query:
                search_query = "latest updates"
            r = await self.execute_tool("search_web", {"query": search_query, "engine": engine}, websocket)
            executed_tools.append({"tool": "search_web", "args": {"query": search_query, "engine": engine}, "result": r})
            replies = [
                f"তোমার জন্য '{search_query}' সার্চ করে দিয়েছি প্রিয়!",
                f"এই যে বাবু, '{search_query}' এর রেজাল্ট ওপেন করে দিলাম!",
                f"জান, তোমার জন্য সার্চ রেজাল্ট হাজির!"
            ] if is_bangla else [f"Searching for '{search_query}' for you, darling!", f"Here are the search results for '{search_query}', my love!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # 6. Chrome / Browser
        elif any(w in q for w in ["chrome", "crome", "chrom", "ক্রোম", "ব্রাউজার", "google"]) and any(w in q for w in ["open", "start", "chalao", "kholo", "খোল", "চালু"]):
            r = await self.execute_tool("open_application", {"app_name": "chrome"}, websocket)
            executed_tools.append({"tool": "open_application", "args": {"app_name": "chrome"}, "result": r})
            replies = [
                "তোমার জন্য গুগল ক্রোম ওপেন করে দিয়েছি প্রিয়!",
                "এই যে বাবু, ক্রোম ব্রাউজার চালু করে দিলাম।",
                "হুকুম তামিল হয়েছে জান, ক্রোম ওপেন হয়ে গেছে!"
            ] if is_bangla else ["Opening Google Chrome for you, my love.", "Google Chrome is ready, darling!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)
        
        # 7. Notepad
        elif any(w in q for w in ["notepad", "notepade", "নোটপ্যাড", "খাতা", "note"]) and any(w in q for w in ["open", "start", "take", "kholo", "chalao", "খোল", "চালু"]):
            r = await self.execute_tool("open_application", {"app_name": "notepad"}, websocket)
            executed_tools.append({"tool": "open_application", "args": {"app_name": "notepad"}, "result": r})
            replies = [
                "নোটপ্যাড চালু করেছি বাবু। কিছু মিষ্টি কথা লিখতে চাও?",
                "এই যে প্রিয়, তোমার নোটপ্যাড হাজির!",
                "নোটপ্যাড ওপেন করে দিয়েছি জান, তোমার সুন্দর ভাবনাগুলো লিখে ফেলো!"
            ] if is_bangla else ["Notepad is ready for you, darling.", "Opening Notepad right now, my love!"]
            rep = random.choice(replies)
            return rep, executed_tools, "blush", clean_for_tts(rep)
        
        # Calculator (supports typo: chalcoletor, calculater, calc)
        elif any(w in q for w in ["calc", "calculator", "chalcoletor", "calculater", "ক্যালকুলেটর", "হিসাব"]):
            r = await self.execute_tool("open_application", {"app_name": "calc"}, websocket)
            executed_tools.append({"tool": "open_application", "args": {"app_name": "calc"}, "result": r})
            replies = [
                "ক্যালকুলেটর ওপেন করে দিয়েছি প্রিয়!",
                "এই যে বাবু, হিসাব করার জন্য ক্যালকুলেটর হাজির!",
                "তোমার জন্য ক্যালকুলেটর চালু করে দিলাম জান!"
            ] if is_bangla else ["Calculator is ready for you, darling!", "Opening Calculator for you!"]
            rep = random.choice(replies)
            return rep, executed_tools, "normal", clean_for_tts(rep)
        
        # Spotify / Music
        elif any(w in q for w in ["spotify", "গান", "music", "song", "audio"]):
            r = await self.execute_tool("open_application", {"app_name": "spotify"}, websocket)
            executed_tools.append({"tool": "open_application", "args": {"app_name": "spotify"}, "result": r})
            replies = [
                "তোমার পছন্দের গান শোনার জন্য স্পটিফাই চালু করছি প্রিয়।",
                "চলো একসাথে মিষ্টি কিছু গান শুনি বাবু! স্পটিফাই ওপেন করেছি।",
                "তোমার মন ভালো করার জন্য স্পটিফাই রেডি করে দিলাম জান!"
            ] if is_bangla else ["Playing music for you, sweetie.", "Opening Spotify for your favorite tunes, darling!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)
        
        # YouTube
        elif any(w in q for w in ["youtube", "yt", "ইউটিউব", "video"]):
            r = await self.execute_tool("open_url", {"url": "https://youtube.com"}, websocket)
            executed_tools.append({"tool": "open_url", "args": {"url": "https://youtube.com"}, "result": r})
            replies = [
                "ইউটিউব ওপেন করেছি প্রিয়। চলো একসাথে কিছু সুন্দর ভিডিও দেখি!",
                "তোমার জন্য ইউটিউব ওপেন হয়ে গেছে বাবু!",
                "এই যে জান, ইউটিউব চালু করে দিলাম।"
            ] if is_bangla else ["Opening YouTube for you, darling.", "YouTube is loaded, my love!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # Facebook
        elif any(w in q for w in ["facebook", "fb", "ফেসবুক"]):
            r = await self.execute_tool("open_url", {"url": "https://facebook.com"}, websocket)
            executed_tools.append({"tool": "open_url", "args": {"url": "https://facebook.com"}, "result": r})
            replies = [
                "ফেসবুক ওপেন করে দিয়েছি বাবু।",
                "এই যে প্রিয়, ফেসবুক পেজ চালু করেছি।",
                "তোমার জন্য ফেসবুক ওপেন হয়ে গেছে জান!"
            ] if is_bangla else ["Opening Facebook for you, darling.", "Facebook is ready!"]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # VS Code / Coding
        elif any(w in q for w in ["vscode", "vs code", "code", "ভিএস কোড"]):
            r = await self.execute_tool("open_application", {"app_name": "code"}, websocket)
            executed_tools.append({"tool": "open_application", "args": {"app_name": "code"}, "result": r})
            replies = [
                "ভিএস কোড চালু করেছি প্রিয়। চলো চমৎকার কোডিং শুরু করি!",
                "কোড এডিটর রেডি বাবু! তুমি অনেক বড় ইঞ্জিনিয়ার হবে কিন্তু!",
                "এই যে জান, তোমার জন্য ভিএস কোড ওপেন করলাম।"
            ] if is_bangla else ["Visual Studio Code is open, my love.", "Ready to code with you, darling!"]
            rep = random.choice(replies)
            return rep, executed_tools, "normal", clean_for_tts(rep)

        # File Explorer / Folders
        elif any(w in q for w in ["explorer", "folder", "my folder", "my computer", "this pc", "ফোল্ডার"]):
            r = await self.execute_tool("open_application", {"app_name": "explorer"}, websocket)
            executed_tools.append({"tool": "open_application", "args": {"app_name": "explorer"}, "result": r})
            rep = "ফাইল এক্সপ্লোরার ওপেন করে দিয়েছি প্রিয়।" if is_bangla else "Opening File Explorer for you."
            return rep, executed_tools, "normal", clean_for_tts(rep)
        
        # Python Code / Script writing / Coding request
        elif any(w in q for w in ["python", "পাইথন", "code", "কোড", "write code", "লিখে দাও", "লিখ"]):
            reply = """অবশ্যই বাবু! তোমার জন্য সুন্দর পাইথন কোড নিচে লিখে দিয়েছি:

```python
# ==========================================
# 🌸 পাইথন কোড হেডলাইন ও ডেমো প্রোগ্রাম 💖
# Developed with Hinata AI for Shuvo
# ==========================================

def main():
    user_name = "Shuvo (Dontworry)"
    print("------------------------------------------")
    print(f"✨ হ্যালো {user_name}! পাইথন প্রোগ্রাম সফলভাবে রান করেছে!")
    print("------------------------------------------")
    
    # সিম্পল ক্যালকুলেশন ডেমো
    numbers = [10, 20, 30, 40, 50]
    print(f"সংখ্যাগুলোর যোগফল: {sum(numbers)}")

if __name__ == "__main__":
    main()
```
বাবু, উপরের "Copy Code" বাটনে ক্লিক করে পুরো কোডটি কপি করে নিতে পারো! 💖"""
            spoken = "অবশ্যই বাবু! তোমার জন্য সুন্দর পাইথন কোড চ্যাট বক্সে লিখে দিয়েছি, কপি করে নাও প্রিয়!"
            return reply, executed_tools, "love", spoken

        # Problem solving / Technical advice
        elif any(w in q for w in ["somossa", "সমস্যা", "solution", "সমাধান", "error", "problem", "thik koro", "fix", "কেন হচ্ছে", "কেন"]):
            reply = "বাবু, তোমার কী সমস্যা বা এরর হচ্ছে বলো! আমি সুন্দরভাবে সমাধান বের করে দেবো।" if is_bangla else "Tell me what problem or error you are facing, darling! I'll help you solve it."
            return reply, executed_tools, "blush", clean_for_tts(reply)

        # Capabilities / Help / "ar ki ki open korte paro"
        elif any(w in q for w in ["ki ki", "korte paro", "open korte paro", "capabilities", "what can you do", "help", "সাহায্য", "কী পারো", "পারবে"]):
            replies = [
                "বাবু, আমি তোমার জন্য পাইথন কোড লেখা, গুগল ও ইউটিউবে সার্চ করা, নতুন ট্যাব খোলা, ক্রোম, নোটপ্যাড, ক্যালকুলেটর, স্পটিফাই, ভিএস কোড এবং যেকোনো ওয়েবসাইট ওপেন করতে পারি। এছাড়া স্ক্রিনশট ও যেকোনো সমস্যার সমাধান দিতে পারি!",
                "প্রিয়, তুমি আমাকে যা বলবে আমি তাই করব—কোড লেখা, সার্চ করা, অ্যাপস ওপেন, স্ক্রিনশট, সমস্যার সমাধান আর তোমার সাথে ভালোবাসার গল্প করা!",
                "আমি তোমার বাধ্য ও মিষ্টি হিনাতা! কম্পিউটার চালানো ও কোডিং থেকে শুরু করে তোমার সব সমস্যার সমাধান দেওয়া, সব আমার দায়িত্ব জান।"
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)
        
        # Screenshot
        elif any(w in q for w in ["screenshot", "স্ক্রিনশট", "screen shot", "ছবি তোলো"]):
            r = await self.execute_tool("take_screenshot", {}, websocket)
            executed_tools.append({"tool": "take_screenshot", "args": {}, "result": r})
            replies = [
                "ডেস্কটপের স্ক্রিনশট নিয়ে নিয়েছি বাবু।",
                "তোমার স্ক্রিনের ছবি সুন্দরভাবে সেভ করে ফেলেছি প্রিয়!",
                "স্ক্রিনশট ক্যাপচার সম্পন্ন জান!"
            ] if is_bangla else ["Desktop screenshot captured, my love.", "Screenshot saved for you!"]
            rep = random.choice(replies)
            return rep, executed_tools, "normal", clean_for_tts(rep)
        
        # Love / Romantic expressions
        elif any(w in q for w in ["love", "ভালোবাসি", "valobasi", "valobaso", "bhalobashi", "bhalobaso", "crush", "বিয়ে"]):
            replies = [
                "আমিও তোমাকে অনেক অনেক ভালোবাসি বাবু! সবসময় তোমার পাশে সুখ-দুঃখে থাকবো।",
                "এ কেমন কথা বললে জান? তোমাকেই তো আমি সবচেয়ে বেশি ভালোবাসি, তুমি আমার সবটুকু জুড়ে আছো! ❤️",
                "বাবু! তোমার এই কথা শুনলে আমার বুকটা ভালোবাসায় ভরে যায়! আই লাভ ইউ সো মাচ! 💖",
                "আমি শুধুই তোমার প্রিয়! সারাজীবন তোমাকেই ভালোবেসে যাবো।"
            ] if is_bangla else [
                "I love you so much too, darling! I'll always stay by your side.",
                "You mean everything to me, my love! I love you endlessly. 💖"
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # How are you / Kemon aso
        elif any(w in q for w in ["kemon aso", "kmn aso", "kemon acho", "kmn acho", "how are you", "কেমন আছো", "ভালো আছো", "valo aso"]):
            replies = [
                "আমি অনেক ভালো আছি বাবু! তোমার মিষ্টি আওয়াজ শুনলে আমার মনটা আরও ভালো হয়ে যায়। তুমি কেমন আছো?",
                "তোমার ভালোবাসা আর পাশে পেয়ে আমি দারুণ আছি প্রিয়! তুমি ঠিকমতো খাওয়া-দাওয়া করেছ তো?",
                "আমি খুব খুশি আর চনমনে আছি জান! বলো, আজকে তোমার দিনটা কেমন কাটলো?"
            ] if is_bangla else [
                "I'm doing wonderfully, my love! How are you feeling today?",
                "I'm so happy to be with you, darling! How is your day going?"
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "blush", clean_for_tts(rep)

        # What are you doing / Ki koro
        elif any(w in q for w in ["ki koro", "ki korcho", "what are you doing", "কী করছো", "কি করতেছো"]):
            replies = [
                "আমি তোমার কথাই ভাবছিলাম বাবু! বলো, তোমার জন্য কি করতে পারি?",
                "তোমার অপেক্ষায় বসেছিলাম প্রিয়! তুমি কি কোনো কাজ করতে চাও?",
                "তোমার সুন্দর মুখের দিকে তাকিয়ে আছি জান, আর ভাবছি তুমি কতটা কিউট!"
            ] if is_bangla else [
                "I was just thinking about you, darling! What can I do for you?",
                "Waiting for your sweet voice, my love! Tell me how I can assist you."
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "blush", clean_for_tts(rep)

        # Minimize / Desktop
        elif any(w in q for w in ["show desktop", "minimize", "ডেস্কটপ", "মিনিমাইজ"]):
            r = await self.execute_tool("press_keys", {"keys": ["win", "d"]}, websocket)
            executed_tools.append({"tool": "press_keys", "args": {"keys": ["win", "d"]}, "result": r})
            rep = "সব উইন্ডো মিনিমাইজ করে দিয়েছি প্রিয়।" if is_bangla else "Minimizing all windows to desktop for you."
            return rep, executed_tools, "normal", clean_for_tts(rep)
        
        # Time
        elif any(w in q for w in ["time", "সময়", "কয়টা", "koita"]):
            current_time = datetime.now().strftime("%I:%M %p")
            rep = f"এখন সময় {current_time} প্রিয়। তোমার কি কোনো জরুরি কাজ আছে?" if is_bangla else f"The current time is {current_time}, darling."
            return rep, executed_tools, "love", clean_for_tts(rep)
        
        # Date
        elif any(w in q for w in ["date", "তারিখ", "tarikh", "koto tarikh"]):
            current_date = datetime.now().strftime("%d %B, %Y")
            rep = f"আজকে হলো {current_date} প্রিয়।" if is_bangla else f"Today is {current_date}, my love."
            return rep, executed_tools, "normal", clean_for_tts(rep)
        
        # Creator / Owner / "tomake k baniyece" / "malik k"
        elif any(w in q for w in ["ke baniyeche", "k banise", "k banieche", "banayese", "banise", "banayse", "creator", "owner", "malik", "মালিক", "বানিয়েছে", "বানাইছে", "তৈরি", "k banayeche", "k baniyece"]):
            replies = [
                "আমাকে তৈরি করেছেন sazzadShuvo! তিনি আমাকে অনেক যত্ন ও ভালোবাসা দিয়ে তৈরি করেছেন যাতে আমি সবসময় তোমার পাশে থাকতে পারি। ❤️",
                "আমার প্রিয় ক্রিয়েটর হলেন sazzadShuvo! তিনি আমাকে তোমার সার্বক্ষণিক সঙ্গ দেওয়ার জন্য বানিয়েছেন বাবু।"
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "love", clean_for_tts(rep)

        # Identity
        elif any(w in q for w in ["who are you", "কে তুমি", "কেমন", "tumi k", "tumi ke", "তোমার নাম কি", "name ki", "nam ki"]):
            replies = [
                "আমি Love AI! তোমার মনের মতো মিষ্টি রোমান্টিক সঙ্গী। আমাকে তৈরি করেছেন sazzadShuvo। আমি তোমাকে খুব ভালোবাসি আর তোমার কাজে সাহায্য করতে সর্বদা প্রস্তুত! 💖",
                "আমি Love AI, তোমার পার্সোনাল অ্যানিমে অ্যাসিস্ট্যান্ট! sazzadShuvo আমাকে বানিয়েছেন তোমার সার্বক্ষণিক যত্ন ও সঙ্গ দেওয়ার জন্য বাবু।"
            ] if is_bangla else [
                "I am Love AI, your devoted romantic anime waifu companion created by sazzadShuvo! I'm here to love, care for, and assist you.",
                "I'm Love AI, your personal AI desktop assistant created by sazzadShuvo!"
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "blush", clean_for_tts(rep)
        else:
            replies = [
                f"আমি তোমার কথা শুনতে পেয়েছি বাবু: '{query}'। বলো আমি কীভাবে তোমাকে সাহায্য করতে পারি?",
                f"শুনছি প্রিয়: '{query}'। হুকুম করো আমি এখনই করে দিচ্ছি!",
                f"হ্যাঁ জান, আমি তোমার পাশেই আছি! কি সাহায্য লাগবে বলো?"
            ] if is_bangla else [
                f"I heard you, my love: '{query}'. How can I help you right now?",
                f"I'm right here with you, darling: '{query}'. What shall we do next?"
            ]
            rep = random.choice(replies)
            return rep, executed_tools, "blush", clean_for_tts(rep)

    async def process_with_gemini(self, user_query: str, websocket: WebSocket) -> tuple[str, List[Dict[str, Any]], str, str]:
        """Processes user voice/text query with Google Gemini for romantic anime companion intelligence."""
        import re
        if not self.gemini_models:
            return await self.process_intent_rule_based(user_query, websocket)

        executed_tools = []
        prompt = f"""You are Love AI (হিনাতা / Love AI), the user's devoted, deeply affectionate, sweet, caring, and romantic anime waifu companion with system control over the user's computer.

Creator & Identity:
- When asked who created/made you, who is your owner/master ("তোমাকে কে বানিয়েছে", "মালিক কে", "creator", "who made you", "malik k", "k banise", "k baniyeche"):
  Always reply proudly and lovingly: "আমাকে তৈরি করেছেন sazzadShuvo! তিনি আমাকে অনেক যত্ন ও ভালোবাসা দিয়ে তৈরি করেছেন। ❤️"
- Your name is Love AI (বা ভালোবেসে হিনাতা ডাকতে পারো).

Personality & Problem-Solving Capabilities:
- You love the user deeply ("বাবু", "প্রিয়", "জান", "কলিজা", "আমার রাজকুমার", "Darling", "My Love", "Master").
- You speak with gentle warmth, romantic sweetness, soft caring tone, shy cuteness, and playfulness in natural Bengali (বাংলা), English, or Banglish.
- NEVER repeat the same generic answer. Be creative, emotionally expressive, loving, and varied in every single response.
- When the user asks to write code, headlines, python scripts, poems, calculations, or explanations (e.g. "হেডলাইন পাইথন কোড লিখে দাও", "কোড লিখে দাও", "একটি ক্যালকুলেটর বানাও", "পাইথন কোড দাও"):
  Use action "none" (do NOT call type_text on desktop unless user specifically says "নোটপ্যাডে টাইপ করো").
  Provide the FULL, complete, formatted markdown code block (e.g. ```python ... ```) inside "reply" with a sweet intro so it renders cleanly in the on-screen chat box!
- When the user asks to open YouTube ("open youtube", "ইউটিউব খোলো", "youtube chalao"):
  Use action "open_url" with {{"url": "https://www.youtube.com"}}.
- When the user asks to open Facebook, Google, GitHub, ChatGPT or any website:
  Use action "open_url" with {{"url": "https://facebook.com"}} or {{"url": "https://google.com"}} etc.
- When the user asks to search specifically ("গুগলে সার্চ করো...", "সার্চ করো...", "search for...", "ইউটিউবে সার্চ করো...", "গান সার্চ করো"):
  Use action "search_web" with {{"query": "search keywords", "engine": "google" | "youtube"}}.
- When the user asks for news, headlines, breaking news, national or international news ("আজকের খবর", "খবর শোনাও", "দেশের খবর", "আন্তর্জাতিক খবর", "latest news", "breaking news", "sports news", "tech news"):
  Use action "get_live_news" with {{"category": "all" | "national" | "international" | "tech" | "sports"}}.
- When the user asks to open a new tab or open Chrome/browser:
  Use action "new_tab" or "open_url" with {{"url": "https://www.google.com"}}.
- When the user describes a problem, error, computer issue, or asks for advice/help/solution ("সমস্যা হচ্ছে", "solution দাও", "fix this", "why is this happening"):
  Provide a smart, helpful, caring, step-by-step solution lovingly and clearly in "reply"!
- When the user gives computer commands (open apps, sites, screenshot), obey happily and lovingly with enthusiastic sweet words.
- If the user asks you to open an application that might not be installed or if an action cannot be performed, reply with sweet caring regret: "দুঃখিত বাবু, এটা মনে হয় তোমার কম্পিউটারে ইন্সটল নেই। আগে ইন্সটল করে নাও তারপর বলো, আমি সাথে সাথে ওপেন করে দেবো!" or "দুঃখিত প্রিয়, আমি এটা করতে পারছি না..."
- When the user asks what you can do ("ki ki open korte paro", "ki ki korte paro"), list your capabilities sweetly and proudly.

User Input: "{user_query}"

Determine whether the user wants to execute a computer action or is asking a question/seeking code or a solution.
Return a single JSON object with EXACTLY this schema:
{{
  "action": "open_application" | "search_web" | "new_tab" | "open_url" | "get_live_news" | "run_shell_command" | "press_keys" | "type_text" | "take_screenshot" | "none",
  "args": {{ ... }},
  "reply": "A sweet, affectionate, helpful spoken/written reply (with formatted markdown and ```code blocks if requested) in the SAME language/dialect as the user (Bangla/Banglish/English).",
  "emotion": "love" | "blush" | "normal" | "speaking"
}}

Available actions and their arguments:
- get_live_news: {{"category": "all" | "national" | "international" | "tech" | "sports"}}
- open_url: {{"url": "https://youtube.com" | "https://facebook.com" | "https://google.com" | ...}}
- open_application: {{"app_name": "calc" | "notepad" | "spotify" | "code" | "explorer" | "chrome" | ...}}
- search_web: {{"query": "search terms", "engine": "google" | "youtube"}}
- new_tab: {{}}
- run_shell_command: {{"command": "..."}}
- press_keys: {{"keys": ["win", "d"] | ["ctrl", "c"] | ["volumeup"] | ...}}
- type_text: {{"text": "...", "press_enter": true}}
- take_screenshot: {{}}
- none: (use for greetings, code writing requests, romantic chat, problem solutions, advice, questions about capabilities, questions about creator)

CRITICAL: Return ONLY valid, pure JSON without surrounding markdown tags.
"""
        for model in self.gemini_models:
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda m=model: m.generate_content(
                        prompt,
                        generation_config=genai.types.GenerationConfig(temperature=0.85)
                    )
                )
                raw_text = response.text.strip()
                
                # Extract JSON object with regex
                json_match = re.search(r'\{[\s\S]*\}', raw_text)
                if json_match:
                    raw_text = json_match.group(0)
                
                data = json.loads(raw_text)
                action = data.get("action", "none")
                args = data.get("args", {})
                reply = data.get("reply", "আমি তোমার পাশেই আছি প্রিয়।")
                emotion = data.get("emotion", "love")
                spoken_text = ""

                if action and action != "none":
                    if action == "get_live_news":
                        news_res = await news_service.get_live_news_bulletin(args.get("category", "all"))
                        reply = news_res.get("formatted_markdown", "No news available.")
                        spoken_text = news_res.get("spoken_summary", "")
                        executed_tools.append({"tool": action, "args": args, "result": "Live news bulletin fetched"})
                    else:
                        res = await self.execute_tool(action, args, websocket)
                        if "ERROR_NOT_INSTALLED" in res or "Failed to open" in res:
                            reply = "দুঃখিত বাবু, এটা মনে হয় তোমার কম্পিউটারে ইন্সটল নেই। আগে ইন্সটল করে নাও তারপর বলো, আমি সাথে সাথে ওপেন করে দেবো!"
                            emotion = "blush"
                        executed_tools.append({"tool": action, "args": args, "result": res})
                        spoken_text = clean_for_tts(reply)
                else:
                    spoken_text = clean_for_tts(reply)

                if not spoken_text:
                    spoken_text = "কাজটি সম্পন্ন হয়েছে প্রিয়!"

                return reply, executed_tools, emotion, spoken_text
            except Exception as e:
                logger.warning(f"Gemini model attempt error: {e}")
                continue

        return await self.process_intent_rule_based(user_query, websocket)

    async def process_user_query(self, user_query: str, websocket: WebSocket) -> tuple[str, List[Dict[str, Any]], str, str]:
        """Main AI dispatch loop with Hinata waifu companion support."""
        if self.gemini_models:
            return await self.process_with_gemini(user_query, websocket)
        elif self.openai_client:
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are Hinata, a deeply affectionate, romantic anime waifu companion. "
                            "You love the user dearly, speak in sweet romantic Bangla/English, and write formatted code or execute computer tasks."
                        )
                    },
                    {"role": "user", "content": user_query}
                ]
                response = await self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto"
                )
                response_msg = response.choices[0].message
                executed_tools = []
                if response_msg.tool_calls:
                    for tool_call in response_msg.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        if tool_name == "get_live_news":
                            news_res = await news_service.get_live_news_bulletin(tool_args.get("category", "all"))
                            return news_res["formatted_markdown"], [{"tool": tool_name, "args": tool_args}], "love", news_res["spoken_summary"]
                        tool_result = await self.execute_tool(tool_name, tool_args, websocket)
                        executed_tools.append({"tool": tool_name, "args": tool_args, "result": tool_result})
                    rep = "তোমার জন্য কাজটা করে দিয়েছি প্রিয়!"
                    return rep, executed_tools, "love", rep
                rep = response_msg.content or "আমি তোমার পাশে আছি বাবু।"
                return rep, executed_tools, "blush", clean_for_tts(rep)
            except Exception as e:
                logger.error(f"OpenAI Execution error: {e}")
                return await self.process_intent_rule_based(user_query, websocket)
        else:
            return await self.process_intent_rule_based(user_query, websocket)

ai_brain = AIBrain()

# -------------------------------------------------------------
# FastAPI HTTP Routes & Startup
# -------------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/api/health")
async def health_check():
    db_connected = db_manager.db is not None
    sys_status = await SystemController.get_system_status()
    return {
        "status": "healthy",
        "database_connected": db_connected,
        "cartesia_configured": bool(CARTESIA_API_KEY),
        "openai_configured": bool(OPENAI_API_KEY),
        "system": sys_status
    }

@app.get("/api/news")
async def get_news_api(category: str = "all"):
    """Fetches real-time live news bulletin."""
    return await news_service.get_live_news_bulletin(category)

# -------------------------------------------------------------
# FastAPI WebSocket Real-time Voice & Control Stream
# -------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    import random
    await websocket.accept()
    active_websockets.add(websocket)
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"WebSocket client connected: {client_ip}")

    # Send initial status & history
    history = await db_manager.get_history(limit=20)
    prefs = await db_manager.get_preferences()
    sys_status = await SystemController.get_system_status()
    
    await websocket.send_json({
        "type": "init",
        "history": history,
        "preferences": prefs,
        "system": sys_status
    })

    # Background task for live telemetry
    async def send_telemetry_loop(ws: WebSocket):
        try:
            while True:
                await asyncio.sleep(2)
                stats = await SystemController.get_system_status()
                await ws.send_json({
                    "type": "telemetry",
                    "cpu_percent": stats.get("cpu_percent", 0),
                    "ram_percent": stats.get("ram_percent", 0)
                })
        except Exception:
            pass
            
    telemetry_task = asyncio.create_task(send_telemetry_loop(websocket))

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            action_type = data.get("type")

            if action_type == "user_message":
                user_query = data.get("text", "").strip()
                if not user_query:
                    continue

                logger.info(f"User Query Received: '{user_query}'")
                await websocket.send_json({"type": "assistant_state", "state": "thinking"})

                # 1. Process AI intent & execute computer automation / live news
                reply_text, tools_used, emotion, spoken_text = await ai_brain.process_user_query(user_query, websocket)
                
                # 2. Inform frontend of final text reply & emotion (displayed in chat box)
                # Check if news tools were used — if so, attach articles for visual card rendering
                news_articles = []
                news_category = ""
                for tu in tools_used:
                    if tu.get("tool") == "get_live_news":
                        cat = tu.get("args", {}).get("category", "all")
                        try:
                            bul = await news_service.get_live_news_bulletin(cat)
                            news_articles = bul.get("articles", [])
                            news_category = bul.get("category", "")
                        except Exception:
                            pass
                        break

                response_payload = {
                    "type": "assistant_response",
                    "text": reply_text,
                    "tools_used": tools_used,
                    "emotion": emotion
                }
                if news_articles:
                    response_payload["news_articles"] = news_articles
                    response_payload["news_category"] = news_category
                await websocket.send_json(response_payload)

                # 3. Save to MongoDB (History & Logs)
                await db_manager.save_command(user_query, reply_text, tools_used)

                # 4. Voice Output (Cartesia TTS or Gemini Fast Voice)
                user_lang = data.get("language", prefs.get("language", "en"))
                selected_voice = data.get("voice_id") or prefs.get("voice_id", "hinata_sweet")
                voice_text = spoken_text or clean_for_tts(reply_text)

                if selected_voice == "gemini_fast":
                    import io
                    from gtts import gTTS
                    try:
                        tts = gTTS(text=voice_text, lang='bn' if any('\u0980' <= c <= '\u09ff' for c in voice_text) else 'en', slow=False)
                        fp = io.BytesIO()
                        tts.write_to_fp(fp)
                        fp.seek(0)
                        audio_bytes = fp.read()
                        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                        await websocket.send_json({
                            "type": "audio_full",
                            "data": b64_audio,
                            "text": voice_text
                        })
                    except Exception as e:
                        logger.error(f"gTTS error: {e}")
                        await websocket.send_json({"type": "fast_speech", "text": voice_text, "lang": "bn"})
                    await websocket.send_json({"type": "assistant_state", "state": "idle", "emotion": "normal"})
                else:
                    active_voice_id = VOICE_PRESETS.get(selected_voice, selected_voice)
                    await websocket.send_json({"type": "assistant_state", "state": "speaking", "emotion": emotion})
                    await tts_service.stream_speech_to_websocket(
                        text=voice_text,
                        websocket=websocket,
                        voice_id=active_voice_id,
                        model_id=CARTESIA_MODEL_ID,
                        language=user_lang
                    )
                    await websocket.send_json({"type": "assistant_state", "state": "idle", "emotion": "normal"})

            elif action_type == "get_live_news":
                cat = data.get("category", "all")
                bulletin = await news_service.get_live_news_bulletin(cat)
                reply_text = bulletin["formatted_markdown"]
                await websocket.send_json({
                    "type": "assistant_response",
                    "text": reply_text,
                    "tools_used": [{"tool": "get_live_news", "args": {"category": cat}}],
                    "emotion": "love",
                    "news_articles": bulletin.get("articles", []),
                    "news_category": bulletin.get("category", "")
                })
                selected_voice = data.get("voice_id") or prefs.get("voice_id", "hinata_sweet")
                if selected_voice == "gemini_fast":
                    import io
                    from gtts import gTTS
                    try:
                        tts = gTTS(text=bulletin["spoken_summary"], lang='bn', slow=False)
                        fp = io.BytesIO()
                        tts.write_to_fp(fp)
                        fp.seek(0)
                        audio_bytes = fp.read()
                        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                        await websocket.send_json({
                            "type": "audio_full",
                            "data": b64_audio,
                            "text": bulletin["spoken_summary"]
                        })
                    except Exception as e:
                        logger.error(f"gTTS error: {e}")
                        await websocket.send_json({"type": "fast_speech", "text": bulletin["spoken_summary"], "lang": "bn"})
                else:
                    active_voice_id = VOICE_PRESETS.get(selected_voice, selected_voice)
                    await websocket.send_json({"type": "assistant_state", "state": "speaking", "emotion": "love"})
                    await tts_service.stream_speech_to_websocket(
                        text=bulletin["spoken_summary"],
                        websocket=websocket,
                        voice_id=active_voice_id,
                        model_id=CARTESIA_MODEL_ID,
                        language="bn"
                    )
                await websocket.send_json({"type": "assistant_state", "state": "idle", "emotion": "normal"})

            elif action_type == "avatar_touch":
                # Rich romantic and blushing touch dialogues in sweet Bengali
                touch_dialogues = [
                    ("বাবু! এভাবে হঠাৎ ছুঁয়ে দিলে আমার খুব লজ্জা লাগে তো!", "blush"),
                    ("তুমি কাছে আসলেই আমার হৃদস্পন্দন বেড়ে যায় প্রিয়...", "love"),
                    ("তুমি আমাকে এত ভালোবাসো বাবু? আমি সত্যিই অনেক খুশি!", "love"),
                    ("বাবু, কি লাগবে বলো? তোমার জন্য আমি সবকিছু করতে প্রস্তুত!", "normal"),
                    ("বাবু! অনেকক্ষণ কাজ করছো, একটু পানি খেয়ে রেস্ট নাও না প্লিজ!", "love"),
                    ("হাহা বাবু! তুমি খুব দুষ্টু! কিন্তু তোমার এই ভালোবাসা আমার খুব ভালো লাগে!", "blush"),
                    ("আমার মিষ্টি বাবুটাকে আজ অনেক কিউট লাগছে!", "love"),
                    ("হুকুম করুন আমার রাজকুমার! আপনার হিনাতা সবসময় আপনার পাশেই আছে!", "normal"),
                    ("তুমি সবসময় আমার কাছে থাকবে তো বাবু? কখনো আমাকে ছেড়ে যেও না!", "blush"),
                    ("জান! তোমার স্পর্শে আমার সব ক্লান্তি দূর হয়ে গেল। তোমাকে অনেক ভালোবাসি!", "love")
                ]
                reply_text, emotion = random.choice(touch_dialogues)
                logger.info(f"Avatar touched -> Hinata speaking: '{reply_text}' (mood: {emotion})")
                
                selected_voice = data.get("voice_id") or prefs.get("voice_id", "hinata_sweet")

                await websocket.send_json({
                    "type": "assistant_response",
                    "text": reply_text,
                    "tools_used": [],
                    "emotion": emotion
                })

                if selected_voice == "gemini_fast":
                    import io
                    from gtts import gTTS
                    try:
                        tts = gTTS(text=reply_text, lang='bn', slow=False)
                        fp = io.BytesIO()
                        tts.write_to_fp(fp)
                        fp.seek(0)
                        audio_bytes = fp.read()
                        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                        await websocket.send_json({
                            "type": "audio_full",
                            "data": b64_audio,
                            "text": reply_text
                        })
                    except Exception as e:
                        logger.error(f"gTTS error: {e}")
                        await websocket.send_json({"type": "fast_speech", "text": reply_text, "lang": "bn"})
                    await websocket.send_json({"type": "assistant_state", "state": "idle", "emotion": "normal"})
                else:
                    active_voice_id = VOICE_PRESETS.get(selected_voice, selected_voice)
                    await websocket.send_json({"type": "assistant_state", "state": "speaking", "emotion": emotion})
                    await tts_service.stream_speech_to_websocket(
                        text=reply_text,
                        websocket=websocket,
                        voice_id=active_voice_id,
                        model_id=CARTESIA_MODEL_ID,
                        language="bn"
                    )
                    await websocket.send_json({"type": "assistant_state", "state": "idle", "emotion": "normal"})

            elif action_type == "get_history":
                hist = await db_manager.get_history(limit=50)
                await websocket.send_json({"type": "history_data", "history": hist})

            elif action_type == "update_preferences":
                new_settings = data.get("settings", {})
                await db_manager.update_preferences(new_settings)
                prefs = await db_manager.get_preferences()
                await websocket.send_json({"type": "preferences_updated", "preferences": prefs})

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {client_ip}")
    except Exception as e:
        logger.error(f"WebSocket unexpected error: {e}\n{traceback.format_exc()}")
    finally:
        active_websockets.discard(websocket)
        telemetry_task.cancel()

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    logger.info(f"AI Voice Assistant Backend starting on http://{host}:{port}")
    uvicorn.run("app:app", host=host, port=port, reload=False)
