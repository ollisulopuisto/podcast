import datetime
import os
import re
import subprocess

def get_current_date_str():
    return datetime.datetime.now().strftime("%Y.%m.%d")

def get_latest_tag():
    try:
        # Get tags matching the calver pattern
        tags = subprocess.check_output(["git", "tag", "--list", "v*"]).decode().splitlines()
        today = get_current_date_str()
        today_tags = [t for t in tags if t.startswith(f"v{today}")]
        if not today_tags:
            return None
        # Sort by the last numeric part
        def sort_key(tag):
            parts = tag.split('.')
            if len(parts) > 3:
                try:
                    return int(parts[3].split('-')[0])
                except:
                    return 0
            return 0
        today_tags.sort(key=sort_key)
        return today_tags[-1]
    except:
        return None

def bump_version():
    today = get_current_date_str()
    latest = get_latest_tag()
    
    if latest and latest.startswith(f"v{today}"):
        parts = latest.split('.')
        if len(parts) > 3:
            # vYYYY.MM.DD.N
            try:
                rev = int(parts[3].split('-')[0])
                new_version = f"v{today}.{rev + 1}"
            except:
                new_version = f"v{today}.1"
        else:
            # vYYYY.MM.DD -> vYYYY.MM.DD.1
            new_version = f"v{today}.1"
    else:
        new_version = f"v{today}.0"
    
    # Update pyproject.toml
    with open("pyproject.toml", "r") as f:
        content = f.read()
    
    new_content = re.sub(r'version = ".*"', f'version = "{new_version.lstrip("v")}"', content)
    
    with open("pyproject.toml", "w") as f:
        f.write(new_content)
        
    return new_version

if __name__ == "__main__":
    v = bump_version()
    print(v)
