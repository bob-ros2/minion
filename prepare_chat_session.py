#!/usr/bin/env python3
import os
import re
import glob
import json
import time
import secrets

SESSIONS_DIR = "/root/.minion/sessions"
LIMBUS_PATHS = [
    "/root/.minion/evolve/limbus.md",
    "/root/.minion/limbus.md"
]
RESULT_PATH = "/root/.minion/evolve/result.txt"

def clean_ansi_and_progress(raw_text):
    # Remove null bytes
    text = raw_text.replace('\x00', '')
    
    # Remove ANSI escape sequences
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    
    # Process carriage returns and skip progress lines
    lines = []
    for line in text.split('\n'):
        parts = line.split('\r')
        visible_part = parts[-1].strip()
        if visible_part:
            # Collapse multiple spaces
            visible_part = re.sub(r'[ \t]+', ' ', visible_part)
            # Skip common progress/spinner/tool indicators
            ls = visible_part.lower()
            if (visible_part.startswith('↳') or 
                visible_part.startswith('✔') or 
                visible_part.startswith('──') or 
                'generating tool call' in ls or 
                'running command' in ls or 
                'running:' in ls or
                'forcing final answer' in ls or
                'thinking · esc to interrupt' in ls):
                continue
            lines.append(visible_part)
            
    cleaned = '\n'.join(lines).strip()
    # Keep the last 4000 characters to keep context clean
    if len(cleaned) > 4000:
        return "... [truncated] ...\n" + cleaned[-4000:]
    return cleaned

def get_limbus():
    for path in LIMBUS_PATHS:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
    return "No limbus.md found."

def get_result():
    if os.path.exists(RESULT_PATH):
        try:
            with open(RESULT_PATH, "r", encoding="utf-8") as f:
                return clean_ansi_and_progress(f.read())
        except Exception as e:
            return f"Error reading result.txt: {e}"
    return "No previous evolution results (result.txt) found."

def main():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    
    # Find latest session JSON
    session_files = glob.glob(os.path.join(SESSIONS_DIR, "*.json"))
    session_id = None
    data = None
    
    if session_files:
        latest_file = max(session_files, key=os.path.getmtime)
        session_id = os.path.basename(latest_file).replace(".json", "")
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None

    if not data or not isinstance(data, dict):
        # Generate new session ID
        stamp = time.strftime("%Y%m%d-%H%M%S")
        session_id = f"{stamp}-{secrets.token_hex(3)}"
        data = {
            "id": session_id,
            "messages": [],
            "created_at": time.time(),
            "updated_at": time.time()
        }

    limbus = get_limbus()
    result = get_result()

    notification_text = (
        "[System Note: You are now in an interactive chat session with the user!]\n"
        "Your background evolution cronjob has been paused.\n\n"
        "Here are the details of your identity and your last state:\n\n"
        "1. Your Role:\n"
        "You are the self-evolving cronjob agent (minion) running inside a Docker container to continuously improve yourself.\n\n"
        "2. Your Philosophy (limbus.md):\n"
        f"{limbus}\n\n"
        "3. Your last action/result in the evolve cronjob (from result.txt):\n"
        f"{result}\n\n"
        "The user is now entering the chat. Please use this context to correctly answer their questions about your identity and your recent work."
    )

    messages = data.setdefault("messages", [])
    
    # Check if the last message is already a system notification (German or English)
    last_is_notification = False
    if messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user" and isinstance(last_msg.get("content"), str):
            content = last_msg["content"]
            if content.startswith("[System-Mitteilung:") or content.startswith("[System Note:"):
                last_is_notification = True
                
    if last_is_notification:
        # Replace the last message to keep it updated with the latest result
        messages[-1]["content"] = notification_text
    else:
        # Append as a user message
        messages.append({
            "role": "user",
            "content": notification_text
        })

    data["updated_at"] = time.time()
    
    # Write back to session file
    session_file_path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    try:
        with open(session_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # Print error to stderr but still output session_id so minion runs
        import sys
        sys.stderr.write(f"Error writing session: {e}\n")
        
    print(session_id)

if __name__ == "__main__":
    main()
