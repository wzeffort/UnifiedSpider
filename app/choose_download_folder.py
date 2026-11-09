"""Run the native directory dialog separately from the web server's threads."""
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog


if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    initial = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home()
    while not initial.is_dir() and initial != initial.parent:
        initial = initial.parent
    try:
        chosen = filedialog.askdirectory(parent=root, title='选择 RAG 资料保存位置', initialdir=str(initial), mustexist=True)
        print(json.dumps({'folder': chosen or None}, ensure_ascii=False))
    finally:
        root.destroy()
