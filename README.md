# 💖 Love AI Voice Assistant (Hinata) 💖

![Love AI Banner](https://img.shields.io/badge/AI-Voice_Assistant-ff69b4?style=for-the-badge&logo=openai) ![Python](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi)

An advanced, romantic, and highly interactive **Anime Waifu (Hinata) AI Voice Assistant** with a stunning **Premium Glassmorphism Aesthetic** interface. Powered by **Google Gemini** for intelligent conversations and **Cartesia AI** for ultra-realistic voice synthesis.

---

## ✨ Features
- **Ultra-Realistic Voice Synthesis:** High-quality TTS powered by Cartesia AI with fallback options.
- **Premium UI/UX:** A stunning Glassmorphism Sci-Fi dashboard with glowing neon auras and smooth animations.
- **Desktop Automation:** Integrated with `pyautogui` to open software, type code, and execute desktop commands!
- **Live System Telemetry:** Real-time visual tracking of your PC's CPU & RAM usage.
- **Live News Updates:** Fetches and reads real-time news headlines (Bangladesh & Global).
- **Interactive Avatar:** Hinata responds dynamically to touches, emotions, and chats.

---

## 🛠️ Prerequisites
Before running this project on your local machine, ensure you have:
1. **Python 3.9+** installed.
2. A **Google Gemini API Key** (Get it from Google AI Studio).
3. A **Cartesia AI API Key** (For realistic voice).
4. A **MongoDB Atlas URI** (For saving chat history).

---

## 🚀 How to Run Locally (User Manual)

Follow these simple steps to install and run the AI on your own computer!

### 1️⃣ Clone the Repository
Open your terminal (or Command Prompt) and run:
```bash
git clone https://github.com/Shazzedshuvo/Love-AI-Voice-Assistant.git
cd Love-AI-Voice-Assistant
```

### 2️⃣ Install Dependencies
Install all the required Python libraries using pip:
```bash
pip install -r requirements.txt
```

### 3️⃣ Setup Environment Variables (API Keys)
Create a new file named `.env` in the root folder of the project.
Add your secret API keys inside the `.env` file like this:
```env
# Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here

# Cartesia AI API Key (For Voice)
CARTESIA_API_KEY=your_cartesia_api_key_here

# MongoDB Connection String (For Chat History)
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
```
*(**Note:** Do not share your `.env` file with anyone! It is ignored by Git automatically.)*

### 4️⃣ Start the AI Server
Run the FastAPI backend server:
```bash
python app.py
```

### 5️⃣ Open the Dashboard
Once the server starts, open your web browser and go to:
👉 **[http://localhost:8000](http://localhost:8000)**

*(Make sure you give microphone permission to your browser so you can talk to Hinata!)*

---

## ⚠️ Important Note About Deployment
**Do NOT deploy this code to a cloud server (like Render, Heroku, or Vercel) as-is!**
This assistant uses `pyautogui` for desktop automation (like opening Chrome or tracking mouse movements). Cloud servers do not have monitors or desktop environments, so running this in the cloud will cause it to crash. **This project is specifically designed to run on a local PC.**

---
*Created with ❤️ by ShazzedShuvo*
