import re
import os

files_to_clean = [
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\new_backend.py",
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\option_chain_handler.py",
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\breakout_strategy.py",
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\position_manager.py",
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\FLATTRADE.py",
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\bi_rpc.py",
    r"c:\Users\aksha\OneDrive\Documents\NF_ALL_eel\Working Backup Copy 2026\NorenWebApi.py"
]

def clean_file(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove import logging
    content = re.sub(r'^import logging\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^from logging import.*\n?', '', content, flags=re.MULTILINE)
    
    # Remove logging setup
    content = re.sub(r'^logging\.basicConfig.*\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^logger =.*\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^logger\.setLevel.*\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^logger\.addHandler.*\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'^file_handler =.*\n?', '', content, flags=re.MULTILINE)

    # Remove log calls (handles simple one-liners and some multiline)
    # This is tricky without a real parser, but we'll try to match logger.(info|error|debug|warning|critical)\(
    # and then find the matching closing paren.
    
    lines = content.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.search(r'^\s*logger\.(info|error|debug|warning|critical|warning|exception)\(', line):
            # Check for block closure
            indent = line[:len(line) - len(line.lstrip())]
            
            # Start of a log call. Find the end by balancing parens.
            open_count = 0
            temp_i = i
            found_end = False
            while temp_i < len(lines):
                open_count += lines[temp_i].count('(')
                open_count -= lines[temp_i].count(')')
                if open_count <= 0:
                    found_end = True
                    break
                temp_i += 1
            
            if found_end:
                # Check context: if preceded by ':' (like if, except, def) and no other lines follow in that block
                # we need a 'pass'
                needs_pass = False
                # Peek back
                prev_i = i - 1
                while prev_i >= 0 and lines[prev_i].strip() == "":
                    prev_i -= 1
                if prev_i >= 0 and lines[prev_i].strip().endswith(':'):
                    # Check if anything else follows in same indent level or deeper
                    # after the logger call ends
                    next_i = temp_i + 1
                    while next_i < len(lines) and lines[next_i].strip() == "":
                        next_i += 1
                    
                    if next_i >= len(lines):
                        needs_pass = True
                    else:
                        next_indent = lines[next_i][:len(lines[next_i]) - len(lines[next_i].lstrip())]
                        if len(next_indent) < len(indent) + 1: # Basic heuristic
                             needs_pass = True
                
                if needs_pass:
                    new_lines.append(indent + "pass")
                
                i = temp_i + 1
                continue
        new_lines.append(line)
        i += 1
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(new_lines) + "\n")

if __name__ == "__main__":
    for f in files_to_clean:
        try:
            clean_file(f)
            print(f"Cleaned {f}")
        except Exception as e:
            print(f"Failed to clean {f}: {e}")
