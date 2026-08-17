import os
import re

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
        print(f"File not found: {filepath}")
        return

    print(f"Cleaning {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    skip_next = False
    
    # Simple regex for matching logger calls (handles some multiline cases if they end with ) on same line)
    # However, multiline logger calls are common.
    # A better way is to identify lines starting with logger. and remove them.
    # And specifically handle indented pass if the block becomes empty.

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Patterns to remove
        remove_patterns = [
            r"import logging",
            r"from logging import",
            r"logger =",
            r"logger\.addHandler",
            r"logger\.setLevel",
            r"file_handler =",
            r"logging\.basicConfig",
            r"logger\.info\(",
            r"logger\.error\(",
            r"logger\.debug\(",
            r"logger\.warning\(",
            r"logger\.critical\("
        ]
        
        should_remove = False
        for pattern in remove_patterns:
            if re.search(pattern, stripped):
                should_remove = True
                break
        
        if should_remove:
            # Check if this is a multiline call (rudimentary check for balanced parens if needed, 
            # but usually it's easier to just see if it ends with ) )
            # If it's a multiline logger call, we need to swallow subsequent lines until )
            if "(" in stripped and ")" not in stripped:
                # Potential multiline
                open_count = stripped.count("(")
                close_count = stripped.count(")")
                while open_count > close_count and i + 1 < len(lines):
                    i += 1
                    open_count += lines[i].count("(")
                    close_count += lines[i].count(")")
            
            # Check if this removal leaves an empty block (e.g. after 'except:' or 'if ...:')
            # We look at the next non-empty line or see if the current line was the only one in the block.
            # This is complex to do perfectly without a parser, but we can replace with 'pass' to be safe.
            
            # If the previous line ended with : and this line belongs to that block
            # we might need a 'pass'.
            indent = line[:len(line) - len(line.lstrip())]
            
            # Simple heuristic: if the next line is less indented or i is last line, add pass
            is_last_line_in_block = True
            if i + 1 < len(lines):
                next_line = lines[i+1]
                if next_line.strip() == "":
                    # Peek further
                    k = i + 2
                    while k < len(lines) and lines[k].strip() == "":
                        k += 1
                    if k < len(lines):
                        next_indent = lines[k][:len(lines[k]) - len(lines[k].lstrip())]
                        if len(next_indent) > len(indent):
                             is_last_line_in_block = False
                        elif len(next_indent) == len(indent):
                             is_last_line_in_block = False
                    else:
                        is_last_line_in_block = True
                else:
                    next_indent = next_line[:len(next_line) - len(next_line.lstrip())]
                    if len(next_indent) > len(indent):
                        is_last_line_in_block = False
                    elif len(next_indent) == len(indent):
                        is_last_line_in_block = False
            
            # If we think it's the only line in the block (simple check)
            if i > 0:
                prev_line = lines[i-1].rstrip()
                while i > 0 and prev_line == "" :
                    i -= 1
                    prev_line = lines[i-1].rstrip()
                if prev_line.endswith(":"):
                    new_lines.append(indent + "pass\n")
            
            i += 1
            continue
        
        new_lines.append(line)
        i += 1

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f"Done cleaning {filepath}")

if __name__ == "__main__":
    for f in files_to_clean:
        clean_file(f)
