#!/usr/bin/env python3
"""
One-command setup wizard for creating a new Claude Code Slack bot.

Usage:
    python setup.py

The wizard will:
1. Ask for bot name and workspace details
2. Open api.slack.com in your default browser
3. Walk you through app creation from manifest
4. Ask you to paste back the tokens
5. Write the env file
6. Optionally launch the bot
"""

import json
import os
import re
import sys
import shutil
import subprocess
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
ENVS_DIR = PROJECT_DIR / "envs"

# ── Helpers ──────────────────────────────────────────────────────────────────

def bold(t):   return f"\033[1m{t}\033[0m"
def green(t):  return f"\033[32m{t}\033[0m"
def yellow(t): return f"\033[33m{t}\033[0m"
def red(t):    return f"\033[31m{t}\033[0m"
def cyan(t):   return f"\033[36m{t}\033[0m"
def dim(t):    return f"\033[2m{t}\033[0m"

def banner():
    print()
    print(bold("╔══════════════════════════════════════════════════════╗"))
    print(bold("║") + cyan("   Claude Code Slack Bot — Setup Wizard              ") + bold("║"))
    print(bold("╚══════════════════════════════════════════════════════╝"))
    print()

def prompt(question, default=None):
    suffix = f" [{default}]" if default else ""
    answer = input(f"  {question}{suffix}: ").strip()
    return answer or default

def confirm(question, default=True):
    hint = "Y/n" if default else "y/N"
    answer = input(f"  {question} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")

def step(n, msg):
    print(f"\n  {bold(cyan(f'[{n}]'))} {msg}")

def wait_msg(msg):
    print(f"      {dim(msg)}")

def success(msg):
    print(f"      {green('✓')} {msg}")

def warn(msg):
    print(f"      {yellow('⚠')} {msg}")

def fail(msg):
    print(f"      {red('✗')} {msg}")
    sys.exit(1)

def pause(msg="→ Press ENTER to continue..."):
    input(f"      {bold(msg)}")

def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    # macOS
    try:
        p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
        p.communicate(text.encode())
        if p.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    # Linux
    for cmd in (['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            p.communicate(text.encode())
            if p.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


# ── Pre-flight checks ────────────────────────────────────────────────────────

def check_claude():
    """Find the claude CLI binary."""
    claude = shutil.which("claude")
    if claude:
        return claude
    nvm_claude = Path.home() / ".nvm" / "versions" / "node"
    if nvm_claude.exists():
        for node_dir in sorted(nvm_claude.iterdir(), reverse=True):
            candidate = node_dir / "bin" / "claude"
            if candidate.exists():
                return str(candidate)
    return None


# ── Manifest generation ──────────────────────────────────────────────────────

def generate_manifest(bot_name: str, display_name: str, description: str) -> str:
    slug = re.sub(r'[^a-z0-9-]', '-', display_name.lower()).strip('-')
    manifest = {
        "display_information": {
            "name": bot_name,
            "description": description,
            "background_color": "#4A154B",
        },
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "assistant_view": {
                "assistant_description": description,
            },
            "bot_user": {
                "display_name": slug,
                "always_online": True,
            },
        },
        "oauth_config": {
            "scopes": {
                "bot": [
                    "app_mentions:read",
                    "assistant:write",
                    "channels:history",
                    "channels:read",
                    "chat:write",
                    "files:read",
                    "files:write",
                    "groups:history",
                    "groups:read",
                    "groups:write",
                    "im:history",
                    "im:read",
                    "im:write",
                    "reactions:read",
                    "reactions:write",
                    "users:read",
                ],
            },
        },
        "settings": {
            "event_subscriptions": {
                "bot_events": [
                    "app_mention",
                    "assistant_thread_context_changed",
                    "assistant_thread_started",
                    "message.channels",
                    "message.groups",
                    "message.im",
                ],
            },
            "interactivity": {"is_enabled": True},
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
        },
    }
    return json.dumps(manifest, indent=2)


# ── Guided browser walkthrough ───────────────────────────────────────────────

def run_browser_setup(manifest_json: str) -> dict:
    """Walk the user through Slack app creation in their own browser."""
    tokens = {"bot_token": None, "app_token": None}

    # ── Step 3: Open Slack API ────────────────────────────────────────
    step(3, "Opening Slack API in your browser...")
    webbrowser.open("https://api.slack.com/apps")
    wait_msg("Your browser should open to api.slack.com/apps.")
    wait_msg("Log in if prompted, then come back here.")
    pause("→ Press ENTER when you are on the 'Your Apps' page...")

    # ── Step 4: Create app from manifest ─────────────────────────────
    step(4, "Create app from manifest")
    wait_msg("In the browser:")
    wait_msg("  1. Click  'Create New App'")
    wait_msg("  2. Choose 'From an app manifest'")
    wait_msg("  3. Select your workspace, then click Next")
    pause("→ Press ENTER when you reach the manifest editor...")

    # ── Step 5: Paste manifest ────────────────────────────────────────
    step(5, "Paste the app manifest")
    copied = copy_to_clipboard(manifest_json)
    if copied:
        success("Manifest copied to clipboard — paste it with Cmd+V / Ctrl+V")
    else:
        warn("Could not copy automatically. Here is the manifest to paste:")
    print()
    for line in manifest_json.split('\n'):
        print(f"        {line}")
    print()
    if copied:
        wait_msg("Switch to the JSON tab, clear the existing content,")
        wait_msg("paste with Cmd+V / Ctrl+V (already in your clipboard), then click Next → Create.")
    else:
        wait_msg("Switch to the JSON tab, clear the existing content,")
        wait_msg("paste the manifest above, then click Next → Create.")
    pause("→ Press ENTER after the app has been created...")

    # ── Step 6: Generate App-Level Token ─────────────────────────────
    step(6, "Generate an App-Level Token (for Socket Mode)")
    wait_msg("On the Basic Information page:")
    wait_msg("  1. Scroll down to 'App-Level Tokens'")
    wait_msg("  2. Click 'Generate Token and Scopes'")
    wait_msg("  3. Name it:  socket-mode")
    wait_msg("  4. Add scope:  connections:write")
    wait_msg("  5. Click Generate — you'll see a token starting with  xapp-")
    print()
    app_token = None
    while not app_token or not app_token.startswith("xapp-"):
        app_token = prompt("Paste the App-Level Token (xapp-...)").strip()
        if not app_token.startswith("xapp-"):
            warn("Token should start with 'xapp-', try again.")
    tokens["app_token"] = app_token
    success(f"App Token saved ({app_token[:20]}...)")

    # ── Step 7: Install app & get Bot Token ──────────────────────────
    step(7, "Install the app to your workspace")
    wait_msg("In the left sidebar click 'Install App',")
    wait_msg("then click 'Install to Workspace' and Allow.")
    wait_msg("You'll be shown the  Bot User OAuth Token  (starts with xoxb-).")
    print()
    bot_token = None
    while not bot_token or not bot_token.startswith("xoxb-"):
        bot_token = prompt("Paste the Bot User OAuth Token (xoxb-...)").strip()
        if not bot_token.startswith("xoxb-"):
            warn("Token should start with 'xoxb-', try again.")
    tokens["bot_token"] = bot_token
    success(f"Bot Token saved ({bot_token[:20]}...)")

    return tokens


# ── Env file creation ────────────────────────────────────────────────────────

def write_env_file(agent_slug: str, tokens: dict, channel_id: str, claude_path: str):
    ENVS_DIR.mkdir(exist_ok=True)
    env_path = ENVS_DIR / f"{agent_slug}.env"

    content = f"""# {agent_slug} — auto-generated by setup.py
SLACK_BOT_TOKEN={tokens['bot_token']}
SLACK_APP_TOKEN={tokens['app_token']}
SLACK_CHANNEL_ID={channel_id}

ALLOWED_USERS=
CLAUDE_WORKSPACE={PROJECT_DIR}
CLAUDE_PATH={claude_path}
GROUP_POLICY=open
"""
    env_path.write_text(content)
    success(f"Written to {env_path}")
    return env_path


# ── Main wizard ──────────────────────────────────────────────────────────────

def main():
    banner()

    step(0, "Pre-flight checks")
    claude_path = check_claude()
    if claude_path:
        success(f"Claude CLI found: {claude_path}")
    else:
        warn("Claude CLI not found in PATH.")
        claude_path = prompt("Path to claude binary", "/usr/local/bin/claude")

    step(1, "Bot configuration")
    bot_name = prompt("Bot display name (shown in Slack)", "Claude Assistant")
    description = prompt("Bot description", "Claude Code powered Slack assistant")
    agent_slug = re.sub(r'[^a-z0-9-]', '-', bot_name.lower()).strip('-')
    agent_slug = prompt("Agent slug (for env file name)", agent_slug)

    env_path = ENVS_DIR / f"{agent_slug}.env"
    if env_path.exists():
        if not confirm(f"{env_path} already exists. Overwrite?", default=False):
            fail("Aborted.")

    step(2, "Generating app manifest")
    manifest_json = generate_manifest(bot_name, bot_name, description)
    success("Manifest ready")
    print()
    for line in manifest_json.split('\n')[:8]:
        print(f"      {dim(line)}")
    print(f"      {dim('...')}")
    print()

    tokens = run_browser_setup(manifest_json)

    step(8, "Configuring environment")
    print()
    wait_msg("Optional: set a default channel/DM the bot sends messages TO (e.g. upload results).")
    wait_msg("The bot listens everywhere it's invited regardless — you can set this later in the .env.")
    print()
    channel_id = ""
    if confirm("Set a default channel or DM now?", default=False):
        wait_msg("In the Slack app:")
        wait_msg("  • Channel: right-click a channel → Copy Link → last segment (C...)")
        wait_msg("  • DM:      right-click your name  → Copy Link → starts with D...")
        print()
        channel_id = prompt("Channel or DM ID", "")

    env_path = write_env_file(agent_slug, tokens, channel_id, claude_path)

    step(9, "Done!")
    print()
    print(f"  {green('Your new bot is ready!')} Configuration saved to:")
    print(f"  {bold(str(env_path))}")
    print()
    print(f"  {bold('To launch:')}")
    print(f"    python slack-bot.py --env {env_path}")
    print()
    print(f"  {bold('To monitor:')}")
    print(f"    python monitor.py --env {env_path}")
    print()

    if confirm("Launch the bot now?"):
        print()
        print(f"  Starting bot with {env_path}...")
        print(f"  {dim('Press Ctrl+C to stop')}")
        print()
        os.execvp(sys.executable, [sys.executable, str(PROJECT_DIR / "slack-bot.py"),
                                    "--env", str(env_path)])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {yellow('Setup cancelled.')}\n")
        sys.exit(0)
