import datetime
import re
import subprocess


def get_current_date_str():
    return datetime.datetime.now().strftime("%Y.%m.%d")


def get_commit_count():
    try:
        return int(
            subprocess.check_output(["git", "rev-list", "--count", "HEAD"])
            .decode()
            .strip()
        )
    except Exception:
        return 0


def bump_version():
    today = get_current_date_str()
    # Preference: N is total commit count (N+1 for the upcoming commit)
    count = get_commit_count()
    new_version = f"v{today}.{count + 1}"

    # Update pyproject.toml
    with open("pyproject.toml", "r") as f:
        content = f.read()

    new_content = re.sub(
        r'version = ".*"', f'version = "{new_version.lstrip("v")}"', content
    )

    with open("pyproject.toml", "w") as f:
        f.write(new_content)

    return new_version


if __name__ == "__main__":
    v = bump_version()
    print(v)
