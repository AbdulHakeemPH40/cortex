import re
import sys

def main():
    with open("src/main_window.py", "r", encoding="utf-8") as f:
        lines = f.readlines()

    out_lines = []
    for i, line in enumerate(lines):
        # We need to fix the line: log.debug(f'[MainWindow] Suppressed error: {e}')
        # that was inserted at exactly 12 spaces, but should match the indentation of `except Exception as e:` + 4 spaces
        
        if line.strip() == "log.debug(f'[MainWindow] Suppressed error: {e}')":
            # find the previous line's indentation
            prev = lines[i-1]
            match = re.match(r'^(\s*)except', prev)
            if match:
                indent = match.group(1) + "    "
                out_lines.append(f"{indent}log.debug(f'[MainWindow] Suppressed error: {{e}}')\n")
                continue
        out_lines.append(line)

    with open("src/main_window.py", "w", encoding="utf-8") as f:
        f.writelines(out_lines)

if __name__ == "__main__":
    main()
