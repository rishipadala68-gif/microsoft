import os
import sys

# Add repository root directory to sys.path so 'app' package can be imported on Vercel
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.api.main import app
