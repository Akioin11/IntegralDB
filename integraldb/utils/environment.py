"""
Environment management utilities for IntegralDB
"""

from pathlib import Path
import os
from typing import Optional, Union, Dict
from dataclasses import dataclass

@dataclass
class Paths:
    """Standard paths used across the application"""
    ROOT: Path
    DATA: Path
    ATTACHMENTS: Path
    CREDENTIALS: Path
    CONFIG: Path

def setup_paths(root: Optional[Union[str, Path]] = None) -> Paths:
    """Initialize and create standard directory structure"""
    if root is None:
        root = Path(__file__).parent.parent.parent
    elif isinstance(root, str):
        root = Path(root)
    
    paths = Paths(
        ROOT=root,
        DATA=root / "data",
        ATTACHMENTS=root / "data" / "attachments",
        CREDENTIALS=root / "data" / "credentials",
        CONFIG=root / "config"
    )
    
    # Create directories
    for path in [paths.DATA, paths.ATTACHMENTS, paths.CREDENTIALS, paths.CONFIG]:
        path.mkdir(parents=True, exist_ok=True)
    
    return paths

def load_env_file(env_file: Path) -> Dict[str, str]:
    """Load environment variables from a file"""
    if not env_file.exists():
        return {}
        
    env_vars = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    
    return env_vars

def setup_environment(paths: Paths) -> None:
    """Set up environment variables from various possible locations"""
    # Potential .env file locations in order of precedence
    env_locations = [
        Path.cwd() / ".env",
        paths.ROOT / ".env",
        paths.CONFIG / ".env",
        Path.home() / ".integraldb" / ".env"
    ]
    
    # Load from each location, later files override earlier ones
    env_vars = {}
    for env_file in env_locations:
        env_vars.update(load_env_file(env_file))
    
    # Update environment
    os.environ.update(env_vars)