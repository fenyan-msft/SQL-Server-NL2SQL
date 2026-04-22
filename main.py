"""
Conversational AI Assistant — Entry Point
Run this file to start the application:

    python main.py
"""

import sys
import tkinter as tk
from tkinter import messagebox


def main() -> None:
    # Fail fast with a friendly message if tkinter is broken
    try:
        root_test = tk.Tk()
        root_test.withdraw()
        root_test.destroy()
    except Exception as exc:
        print(f"ERROR: tkinter is not available — {exc}", file=sys.stderr)
        sys.exit(1)

    # Import the window here so that config errors surface with helpful text
    try:
        from ui.login_window import LoginWindow
        from ui.chat_window import ChatWindow
    except ImportError as exc:
        messagebox.showerror(
            title="Import error",
            message=f"Could not load the application:\n\n{exc}\n\n"
                    "Run:  pip install -r requirements.txt",
        )
        sys.exit(1)

    # Show login screen and wait for the user to select a PersonID
    person_id = LoginWindow().run()
    if person_id is None:
        sys.exit(0)

    app = ChatWindow(person_id=person_id)
    app.run()


if __name__ == "__main__":
    main()
