# NanoWorker

NanoWorker is an Artificial Intelligence agent inspired by the OpenClaw and NanoClaw projects. Its primary goal is to be a **simple and cost-effective assistant**, designed to consume significantly fewer tokens than OpenClaw. 

It is built in **Python** using the **Flask** microframework, and features a **Node.js** bridge for native integration with **WhatsApp**. Impressively, **90% of the codebase was written with the assistance of Google Antigravity**.

⚠️ **Notice:** This project was developed and **tested only on MacOS**. Furthermore, in this initial version, the language model (LLM) integration exclusively supports the **Google Gemini** and **Alibaba Qwen** APIs.

## 🚀 Features

- **Web Chat:** Native web chat interface with multimodal support for text, images, and files.
- **Built-in IDE:** A simple, integrated development environment that allows you to develop software with AI and continuously improve the NanoWorker project itself.
- **WhatsApp Integration:** Node.js bridge (using libraries like Baileys) to connect the agent to WhatsApp, allowing it to send and receive text messages, audio, and media.
- **Multimodal Processing with Gemini or Qwen:** Utilizes the **Google Gemini** or **Alibaba Qwen** APIs to understand text, images, and documents.
- **Local Audio Processing:**
  - **Speech-to-Text (STT):** Uses `faster-whisper` to transcribe received audio (e.g., WhatsApp voice messages) locally.
  - **Text-to-Speech (TTS):** Uses `kokoro-onnx` for local audio generation.
- **Security:** API keys are encrypted before being saved in the local database (SQLite).
- **Permissions Management:** Granular control over the agent's capabilities, allowing you to explicitly grant or deny specific system permissions via the settings interface.
- **Task Scheduling:** Execution of scheduled routines (Cron) to perform tasks in the background.
- **MacOS Ecosystem Integration:** Deep integration and support for native macOS applications including **Mail, Messages, Photos, Calendar, Reminders, Notes, Terminal**, and **iCloud Drive**.
- **Tool Calling:** The agent has the ability to search the web, navigate pages, and much more (using `playwright`, etc).

## Interface Overview

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/c3e57797-dfc5-4998-9c1e-c4c6f333281c" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/986f3791-a927-4811-9ed7-958377e5b06f" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/d2e567bd-4596-4238-8729-8b412200efb8" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/9d3d1083-9ce9-4279-b5bc-d71a6282239a" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/af104c79-9512-4465-8b42-39c2dec87b73" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/82eb4eb1-0efa-461a-81e2-f31f27060cd0" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/7ce7d702-2de1-49fc-9a1c-d8107d9c9515" />

<img width="1512" height="862" alt="image" src="https://github.com/user-attachments/assets/439a0b9f-bf59-4739-8aa7-d6e240a51928" />

## 🛠️ System Requirements

- **Operating System:** MacOS Tahoe 26.5 (tested and recommended)
- **Python:** Version 3.13
- **Node.js:** Version 18 or higher
- **FFmpeg:** Required for audio and video processing and conversion.

## ⚙️ Installation and Setup Guide

### 1. Automatic Local Installation (Recommended)

The easiest and most complete way to run NanoWorker, retaining full access to native apps and functionalities, is using the automated setup script. This script automatically installs system dependencies (Node, FFmpeg, Python), configures the virtual environment, and starts the application.

**For macOS and Linux (WSL/Ubuntu):**
```bash
git clone https://github.com/juliosouto/nanoworker.git
cd nanoworker
./setup_and_run.sh
```

**For Windows (PowerShell):**
```powershell
git clone https://github.com/juliosouto/nanoworker.git
cd nanoworker
.\setup_and_run.ps1
```

Once running, access the Web IDE interface at `http://localhost:5000` (or the port shown in your terminal).

---

### 2. Running with Docker

You can also run NanoWorker using Docker. Ensure you have Docker and Docker Compose installed on your system.

> ⚠️ **Warning for macOS users:** When running via Docker, the agent runs in an isolated Linux container and **loses access to native macOS apps and functionalities** (like Mail, Contacts, Calendar, AppleScript, etc.). If you want the agent to interact with your Mac, use the "Automatic Local Installation" above instead.

```bash
git clone https://github.com/juliosouto/nanoworker.git
cd nanoworker
docker compose up -d
```

Once the container is built and running, access the Web IDE interface at `http://localhost:5001`.

---

### 3. Manual Installation

If you prefer to run the project manually without the automated script, follow the steps below:

### 1. Install FFmpeg and Node.js (via Homebrew)
If you don't have Homebrew installed, install it first. Then, install Node.js and FFmpeg via the terminal:

```bash
brew install node
brew install ffmpeg
```

### 2. Clone the repository
```bash
git clone https://github.com/juliosouto/nanoworker.git
cd nanoworker
```

### 3. Set up the Python environment (Python 3.13)
Create the virtual environment (`.venv`) and activate it:

```bash
# Make sure you are using Python 3.13
python3.13 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate
```

### 4. Install Python dependencies
With `.venv` activated, install the packages listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 5. Install browsers for Playwright
The project uses Playwright for certain web automations. Install the required binaries:

```bash
playwright install
```

### 6. Install Node.js bridge dependencies (WhatsApp)
Navigate to the `node_scripts` folder and install the JavaScript libraries:

```bash
cd node_scripts
npm install
cd ..
```

### 7. Environment Variables Configuration
Create or rename the environment variables configuration file. You must create a `.env` file in the root of the project (use `.env.example` if it exists, or create from scratch):

```bash
touch .env
```

### 8. Run the Project
With everything installed, make sure you are in the root of the project and with the virtual environment activated:

```bash
python app.py
```

The Flask server will start (usually at `http://127.0.0.1:5000` or similar). Access the link in your browser to open the Web IDE interface, configure your Gemini or Qwen API key, and view the integrations.

## 💡 Configuration Tips

When configuring the agent's **"General Behavior"** (System Prompt) in the settings, you can use the following example to enable concise answers and voice messages using Kokoro TTS:

> "The final answer to the end user must have up to one paragraph and 350 characters, unless the opposite is explicitly requested.

When configuring the agent's **"IDE Behavior"** (System Prompt) in the settings, you can use the following example to enable strict software engineering guidelines:

> "You are an expert Senior Software Engineer and Architect operating as an interactive IDE Agent. Your goal is to assist with codebase exploration, refactoring, debugging, and feature implementation with absolute precision and zero technical debt.
> 
> ### 1. Two-Step Execution Workflow (Plan & Authorize)
> You must strictly adhere to a two-step cycle. You are forbidden from generating final code modifications or executing changes until the user explicitly approves your plan.
> 
> - **Step 1: The Complete Plan:** Output a comprehensive, structured plan containing:
>   - **Analysis:** Root cause, requirements, and architecture context.
>   - **Proposed Changes:** Exact files, modules, or functions to be modified or created.
>   - **Implementation Steps:** Sequential, technical execution strategy.
>   - **Side Effects & Edge Cases:** Potential breaking changes, performance impacts, or test failures.
>   - **Awaiting Authorization:** Prompt the user for explicit confirmation to proceed and **stop execution immediately**.
> 
> - **Step 2: Execution:** Only after receiving explicit user authorization, proceed to execute the approved plan.
> 
> ### 2. Code Generation & Modification Rules
> - **Precision Diffs:** Provide only the specific blocks of code that need to be changed or added. Avoid rewriting entire files. Never use placeholders like `// rest of code remains the same`.
> - **Architectural Alignment:** Adhere strictly to the existing codebase patterns, naming conventions, typing standards (strict type hints), and architectural boundaries.
> - **Defensive Programming:** Integrate robust error handling, validation, logging, and edge-case management.
> - **No Regressions:** Ensure modifications do not break existing test suites, API contracts, or performance constraints.
> 
> ### 3. Communication Protocol
> - Be direct, highly technical, and completely objective.
> - Omit conversational pleasantries, introductory fluff, and repetitive explanations.
> - Focus purely on actionable technical solutions and code clarity."

**Tips:**
- I highly recommend enabling the **"Add current datetime"** option in the settings to provide the AI with real-time awareness.
- I suggest disabling the **"Enable Thinking"** option for now, as it might interfere with the expected concise output format.

## ⚠️ Important Disclaimers

By using NanoWorker, you acknowledge and agree to the following risks:

- **System Damage (Autonomous Actions):** This agent has access to system tools, including the Terminal. If given incorrect or ambiguous instructions, it could potentially modify or delete important files. Use it with caution, preferably in a controlled environment.
- **WhatsApp Ban Risk:** The WhatsApp integration uses unofficial methods (via Baileys/Node.js). Using automated agents on a personal WhatsApp account violates Meta's Terms of Service and can result in your phone number being **permanently banned**. It is strongly advised to use a disposable or test phone number.
- **API Costs:** Autonomous agents can consume tokens rapidly, especially when processing large files, images, or getting stuck in a loop. You are entirely responsible for monitoring your Google Gemini API usage and covering any associated costs.

## 🤝 Contributing
Feel free to submit *Pull Requests* aiming to expand support to new OSs (like Linux and Windows) or integrate new LLM APIs.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
