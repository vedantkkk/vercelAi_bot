# AI Interview Bot - Technical Mock Interview Platform

An advanced, AI-powered mock interview platform that conducts automated, session-isolated technical interviews with real-time ML-powered proctoring, dynamic coding challenges, and professional performance report generation.

---

## 🚀 Key Features

*   **Tailored Resume Analysis**: Extract skills, projects, certifications, and experience from uploaded PDF/TXT resumes using Gemini AI to dynamically build a personalized question bank.
*   **Conversational Voice Loop**: Conducts interviews using browser-native Speech Synthesis (TTS) and Speech Recognition (STT) for natural conversation.
*   **Hybrid Keyboard Fallback**: Sleek, real-time manual input bar with a microphone mute/unmute control allowing keyboard input fallback at any time.
*   **Real-time ML Proctoring**: Client-side face detection using TensorFlow.js and the BlazeFace model to flag violations (e.g. no face detected, multiple people, tab switching).
*   **Dynamic Coding Challenges**: Easy LeetCode-style programming challenges customized to candidate's preferred language (Python, Java, JavaScript, C++).
*   **Comprehensive PDF Report**: Clean and structured performance PDF report highlighting scores, strengths, coding evaluations, and overall recommendations.

---

## 🛠️ Tech Stack

### Backend
*   **Python 3.8+**
*   **Flask 3.x**: Lightweight HTTP web router
*   **Flask-SocketIO 5.x**: Real-time WebSockets for bidirectional messaging
*   **Google Generative AI (Gemini v1beta/v1)**: Scoped client interface for prompt generation, grading, and coding challenge evaluation
*   **PyPDF2 3.x**: PDF text extraction
*   **ReportLab 4.x**: PDF generation with programmatic layouts
*   **python-dotenv**: Environment configuration manager

### Frontend
*   **HTML5 & CSS3**: Custom modern styling featuring dark/glassmorphic designs and glowing neon micro-animations
*   **JavaScript (ES6+)**: Bidirectional WebSocket bindings, Speech API event-loops, and media controls
*   **TensorFlow.js & BlazeFace**: High-speed, client-side face monitoring (respects user privacy; no video is ever sent to the server)
*   **Socket.IO Client**: Persistent client-server connection

---

## 🏛️ Architecture Overview

The system operates as a single-page reactive application powered by persistent WebSocket events:

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (Client-Side)                    │
│   ┌──────────────┐     ┌───────────────┐     ┌───────────┐  │
│   │ HTML / CSS   │ ─── │ JavaScript    │ ─── │ BlazeFace │  │
│   │ Web Speech   │     │ Socket.IO     │     │ (TF.js ML)│  │
│   └──────────────┘     └───────────────┘     └───────────┘  │
└───────────────────────────────▲─────────────────────────────┘
                                │ WebSocket (Socket.IO Events)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask Server (Backend)                   │
│   ┌──────────────┐     ┌───────────────┐     ┌───────────┐  │
│   │ Flask Routes │     │ Socket handlers│    │ Session   │  │
│   │              │     │ (Async threads)│    │ Manager   │  │
│   └──────────────┘     └───────────────┘     └───────────┘  │
└───────────────────────────────▲─────────────────────────────┘
                                │ HTTPS REST APIs (Scoped Key)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                  Google Gemini AI API                       │
└─────────────────────────────────────────────────────────────┘
```

### Clean Design & Security Patterns
1.  **Session-Isolated Clients**: Rather than using global generative AI configurations (which leaks keys and quotas between concurrent users), the server dynamically binds unique `GenerativeServiceClient` objects using Google's raw schema.
2.  **ReportLab XML Safety**: Dynamically formats report strings using `html.escape` to ensure characters like `&` or brackets do not break ReportLab's XML parser.
3.  **Evaluator Race-Condition Resolution**: Spawns concurrent evaluation threads in the background for efficiency but joins them synchronously before final feedback generation, ensuring no missing scores.

---

## 📂 Folder Structure

```
AI_Interview_bot/
├── .venv/                  # Virtual environment
├── static/
│   ├── css/
│   │   └── style.css       # Premium stylesheets with dark mode & keyframes
│   └── js/
│       └── script.js       # Core socket, video, face-tracking, and speech loop
├── templates/
│   └── index.html          # Main application user interface
├── uploads/                # Directory for temporary resume storage
├── .env.example            # Configuration values guide
├── .gitignore              # Files and folders to exclude from Git
├── app.py                  # Main Flask application entrypoint & session managers
├── Evaluation.txt          # Technical guide & common interview answers
├── README.md               # Product documentation (This file)
└── requirements.txt        # Python library dependencies
```

---

## ⚙️ Installation & Setup

### 1. Prerequisites
Ensure you have **Python 3.8+** installed on your machine.

### 2. Clone and Open
Open your terminal inside the project directory:
```bash
cd AI_Interview_bot
```

### 3. Create & Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
Copy `.env.example` into a new `.env` file:
```bash
cp .env.example .env
```
Open `.env` and fill in your details:
```env
GEMINI_API_KEY=your_gemini_api_key_here
SECRET_KEY=generate_a_random_hex_string
```

---

## 💻 Running Locally

Start the local development server:
```bash
python app.py
```
By default, the server runs on `http://127.0.0.1:5000`. Open this address in your Google Chrome or Microsoft Edge browser (recommended for optimal Web Speech API support).

---

## 🌐 Production Deployment

### Frontend & Backend (Monolith) - Render / Railway
Since this is a Flask application with WebSocket requirements, it should be deployed on a platform supporting persistent connections.

#### Deployment on Render
1.  Sign in to **Render** and click **New > Web Service**.
2.  Connect your Git repository.
3.  Configure parameters:
    *   **Runtime**: `Python`
    *   **Build Command**: `pip install -r requirements.txt`
    *   **Start Command**: `gunicorn --worker-class eventlet -w 1 app:app` (Note: change the server run logic to support eventlet workers or use standard socketio configuration)
4.  Add your environment variables in the **Environment** tab:
    *   `GEMINI_API_KEY` = *your_api_key*
    *   `SECRET_KEY` = *your_secret_key*

---

## 🔮 Future Improvements

1.  **Persistent Database**: Store user profiles, historical report files, and transcripts in a PostgreSQL database (replaces the current in-memory `sessions` dict).
2.  **Dockerization**: Wrap backend services in a container for sandbox-safe code execution and testing.
3.  **Expanded Proctoring**: Add ambient noise detection and eye-tracking alerts to strengthen anti-cheating logs.

---

## 👤 Author
Mock Interview Bot Project - Polished for Interview Evaluation.
