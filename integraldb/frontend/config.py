"""
Frontend configuration module for IntegralDB
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st

# Base paths
PACKAGE_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PACKAGE_ROOT / "data"

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
    
    st.error("No .env file found in standard locations")
    st.stop()

def get_env(name: str, required: bool = True) -> str:
    """Get environment variable with validation"""
    value = os.environ.get(name)
    if required and not value:
        st.error(f"Missing required environment variable: {name}")
        st.stop()
    return value.strip().strip('"').strip("'") if value else None

class Config:
    """Frontend configuration object"""
    
    def __init__(self):
        load_environment()
        
        # API Keys and URLs
        self.GOOGLE_API_KEY = get_env("GOOGLE_API_KEY")
        self.SUPABASE_URL = get_env("SUPABASE_URL")
        self.SUPABASE_KEY = get_env("SUPABASE_KEY")
        
        # UI Settings
        self.PAGE_TITLE = "IntegralDB"
        self.PAGE_ICON = "🔍"
        
        # RAG Settings
        self.MATCH_COUNT = int(get_env("MATCH_COUNT", False) or "5")
        self.MATCH_THRESHOLD = float(get_env("MATCH_THRESHOLD", False) or "0.4")
        
        # Model Settings
        self.EMBEDDING_MODEL = "models/text-embedding-004"
        self.GENERATIVE_MODEL = "gemini-2.5-flash"
        
        # Validate configuration
        self.validate()
    
    def validate(self):
        """Validate the configuration"""
        required_vars = ["GOOGLE_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]
        missing = [var for var in required_vars if not getattr(self, var)]
        if missing:
            st.error(f"Missing required configuration: {', '.join(missing)}")
            st.stop()

# Global config instance
config = Config()