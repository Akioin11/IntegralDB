# Backend service configuration

import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory configurations
PACKAGE_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PACKAGE_ROOT / "data"
ATTACHMENT_DIR = DATA_DIR / "attachments"
CREDENTIALS_DIR = DATA_DIR / "credentials"

# Create necessary directories
DATA_DIR.mkdir(exist_ok=True)
ATTACHMENT_DIR.mkdir(exist_ok=True)
CREDENTIALS_DIR.mkdir(exist_ok=True)

# Environment loading
def load_environment():
    """Load environment variables from multiple potential locations"""
    env_locations = [
        Path.cwd() / ".env",
        PACKAGE_ROOT / ".env",
        Path.home() / ".integraldb" / ".env"
    ]
    
    for env_path in env_locations:
        if env_path.exists():
            load_dotenv(env_path)
            return
    
    raise EnvironmentError("No .env file found in standard locations")

def get_env(name: str, required: bool = True) -> str:
    """Get environment variable with validation"""
    value = os.environ.get(name)
    if required and not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value.strip().strip('"').strip("'") if value else None

class Config:
    """Global configuration object"""
    
    def __init__(self):
        load_environment()
        
        # API Keys and URLs
        self.GOOGLE_API_KEY = get_env("GOOGLE_API_KEY")
        self.SUPABASE_URL = get_env("SUPABASE_URL")
        self.SUPABASE_KEY = get_env("SUPABASE_KEY")
        
        # File paths
        self.CREDENTIALS_PATH = CREDENTIALS_DIR / "credentials.json"
        self.TOKEN_PATH = CREDENTIALS_DIR / "token.json"
        
        # Processing settings
        self.CHUNK_SIZE = int(get_env("CHUNK_SIZE", False) or "1000")
        self.CHUNK_OVERLAP = int(get_env("CHUNK_OVERLAP", False) or "200")
        self.UPDATE_INTERVAL = int(get_env("UPDATE_INTERVAL", False) or "3600")
        
        # Validate configuration
        self.validate()
    
    def validate(self):
        """Validate the configuration"""
        required_vars = ["GOOGLE_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]
        missing = [var for var in required_vars if not getattr(self, var)]
        if missing:
            raise EnvironmentError(f"Missing required configuration: {', '.join(missing)}")

# Global config instance
config = Config()