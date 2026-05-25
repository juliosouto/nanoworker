#!/usr/bin/env bash
set -e

# --- Helper Functions ---
print_info() { echo -e "\n\033[1;34m[INFO]\033[0m $1"; }
print_error() { echo -e "\n\033[1;31m[ERROR]\033[0m $1"; }
print_success() { echo -e "\n\033[1;32m[SUCCESS]\033[0m $1"; }

OS_TYPE=$(uname -s)
print_info "Detected OS: $OS_TYPE"

# --- 1. System Dependencies ---
if [ "$OS_TYPE" = "Darwin" ]; then
    print_info "Checking Homebrew..."
    if ! command -v brew &> /dev/null; then
        print_info "Homebrew not found. Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Load Homebrew to current shell if installed in Apple Silicon default path
        if [ -x /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    fi

    print_info "Installing system dependencies via Homebrew..."
    brew install node ffmpeg

elif [ "$OS_TYPE" = "Linux" ]; then
    print_info "Linux detected. Attempting to install dependencies using apt..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y curl ffmpeg software-properties-common
        
        # Install Node.js (v18+)
        if ! command -v node &> /dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
            sudo apt-get install -y nodejs
        fi

        # Check Python 3.13
        if ! command -v python3.13 &> /dev/null; then
            print_info "Adding deadsnakes PPA for Python 3.13..."
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt-get update
            sudo apt-get install -y python3.13 python3.13-venv python3.13-dev
        fi
    else
        print_error "apt-get not found. This script currently supports Debian/Ubuntu-based Linux distributions."
        exit 1
    fi
else
    print_error "Unsupported Operating System: $OS_TYPE. Only MacOS and Linux are supported."
    exit 1
fi

# --- 2. Python Environment ---
print_info "Setting up Python environment..."
if ! command -v python3.13 &> /dev/null; then
    print_error "Python 3.13 is required but not found. Please install it manually."
    exit 1
fi

if [ ! -d ".venv" ]; then
    print_info "Creating virtual environment .venv..."
    python3.13 -m venv .venv
else
    print_info "Virtual environment .venv already exists."
fi

print_info "Activating virtual environment..."
source .venv/bin/activate

# --- 3. Python Dependencies & Playwright ---
print_info "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

print_info "Installing Playwright browsers..."
playwright install

# --- 4. Node.js Dependencies ---
print_info "Installing Node.js bridge dependencies..."
if [ -d "node_scripts" ]; then
    cd node_scripts
    npm install
    cd ..
else
    print_error "Directory 'node_scripts' not found! Make sure you are running this from the project root."
    exit 1
fi

# --- 5. Environment Variables ---
if [ ! -f ".env" ]; then
    print_info "Creating .env file..."
    touch .env
    print_info "Created empty .env file. Please fill in your keys if required."
else
    print_info ".env file already exists."
fi

# --- 6. Run Application ---
print_success "Installation complete! Starting NanoWorker..."
python app.py
