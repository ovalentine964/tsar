#!/usr/bin/env python3
"""TSAR setup wizard — creates data directory and verifies configuration."""
import os
import sys
from pathlib import Path

def main():
    print("TSAR Setup Wizard")
    print("=" * 40)
    
    # Create data directory
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    print(f"✓ Created {data_dir}/")
    
    # Check .env
    env_file = Path(".env")
    if not env_file.exists():
        example = Path(".env.example")
        if example.exists():
            print("⚠ No .env file found. Copy .env.example to .env and fill in your keys.")
        else:
            print("⚠ No .env or .env.example found.")
    else:
        print("✓ .env file exists")
    
    # Check config
    config_dir = Path("config")
    if config_dir.exists():
        print("✓ config/ directory exists")
    else:
        print("✗ config/ directory missing!")
    
    # Check Python version
    v = sys.version_info
    if v >= (3, 12):
        print(f"✓ Python {v.major}.{v.minor}.{v.micro}")
    else:
        print(f"✗ Python 3.12+ required, got {v.major}.{v.minor}.{v.micro}")
        sys.exit(1)
    
    print("\nSetup complete! Run: python -m src")

if __name__ == "__main__":
    main()
