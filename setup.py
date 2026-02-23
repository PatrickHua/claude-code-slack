#!/usr/bin/env python3
"""
One-command setup wizard for creating a new Claude Code Slack bot.

Usage:
    python setup.py

The wizard will:
1. Ask for bot name and workspace details
2. Open a browser to api.slack.com
3. Automate app creation from manifest
4. Extract tokens
5. Write the env file
6. Optionally launch the bot
"""

import os
import re
import sys
import shutil
import subprocess
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

def _copy_to_clipboard(text: str):
    """Best-effort copy to system clipboard."""
    for cmd in (['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            p.communicate(text.encode())
            if p.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


# ── Pre-flight checks ───────────────────────────────────────────────────────

def check_deps():
    """Ensure Playwright and Chromium are available."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        fail("Playwright not installed. Run: pip install playwright")

    browser_dir = Path.home() / ".cache" / "ms-playwright"
    chromium_dirs = list(browser_dir.glob("chromium-*")) if browser_dir.exists() else []
    if not chromium_dirs:
        print(f"      Installing Chromium browser...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True, capture_output=True)

    # Quick smoke test to see if Chromium can actually launch
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        success("Playwright + Chromium ready")
    except Exception as e:
        if "missing dependencies" in str(e).lower():
            print()
            warn("System libraries missing for Chromium.")
            print(f"      Run this command first, then re-run setup.py:")
            print()
            print(f"        {bold('sudo apt-get install -y libnspr4 libnss3 libasound2t64')}")
            print()
            sys.exit(1)
        raise


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


# ── Manifest generation ─────────────────────────────────────────────────────

def generate_manifest(bot_name: str, display_name: str, description: str) -> str:
    slug = re.sub(r'[^a-z0-9-]', '-', display_name.lower()).strip('-')
    return f"""display_information:
  name: {bot_name}
  description: {description}
  background_color: "#4A154B"

features:
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  assistant_view:
    assistant_description: {description}
  bot_user:
    display_name: {slug}
    always_online: true

oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - assistant:write
      - channels:history
      - channels:read
      - chat:write
      - files:read
      - files:write
      - groups:history
      - groups:read
      - groups:write
      - im:history
      - im:read
      - im:write
      - reactions:read
      - reactions:write
      - users:read

settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - assistant_thread_context_changed
      - assistant_thread_started
      - message.channels
      - message.groups
      - message.im
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
"""

# ── Browser automation ───────────────────────────────────────────────────────

def run_browser_setup(manifest_yaml: str, agent_slug: str):
    """Open browser, create app from manifest, extract tokens."""
    from playwright.sync_api import sync_playwright

    tokens = {"bot_token": None, "app_token": None}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # ── Step: Open Slack API and wait for login ──────────────────
        step(3, "Opening Slack API in browser...")
        page.goto("https://api.slack.com/apps")
        wait_msg("Please log in to your Slack workspace if prompted.")
        wait_msg("Once you see the 'Your Apps' page, press ENTER here.")
        input(f"      {bold('→ Press ENTER when logged in...')}")

        # ── Step: Create New App ─────────────────────────────────────
        step(4, "Creating app from manifest...")

        try:
            create_btn = page.get_by_role("link", name=re.compile(r"Create.*(New|an)?\s*App", re.I))
            if not create_btn.is_visible(timeout=3000):
                create_btn = page.locator("a:has-text('Create New App'), button:has-text('Create New App')").first
            create_btn.click()
            success("Clicked 'Create New App'")
        except Exception:
            warn("Couldn't find 'Create New App' button.")
            wait_msg("Please click 'Create New App' manually.")
            input(f"      {bold('→ Press ENTER after clicking...')}")

        page.wait_for_timeout(1500)

        # Select "From an app manifest"
        try:
            manifest_option = page.locator("text=From an app manifest").first
            manifest_option.wait_for(state="visible", timeout=5000)
            manifest_option.click()
            success("Selected 'From an app manifest'")
        except Exception:
            warn("Couldn't find manifest option.")
            wait_msg("Please select 'From an app manifest' manually.")
            input(f"      {bold('→ Press ENTER after selecting...')}")

        page.wait_for_timeout(2000)

        # ── Step: Select workspace ───────────────────────────────────
        step(5, "Select your workspace...")
        wait_msg("Pick the workspace from the dropdown, then click Next.")
        input(f"      {bold('→ Press ENTER after selecting workspace and clicking Next...')}")

        page.wait_for_timeout(1500)

        # ── Step: Paste manifest ─────────────────────────────────────
        step(6, "Pasting app manifest...")

        # Switch to YAML tab
        try:
            yaml_tab = page.locator("text=YAML").first
            yaml_tab.wait_for(state="visible", timeout=5000)
            yaml_tab.click()
            page.wait_for_timeout(800)
            success("Switched to YAML editor")
        except Exception:
            warn("Couldn't switch to YAML tab — may already be on it.")

        # Clear and paste into the editor via clipboard (much faster than typing)
        pasted = False
        try:
            editor = page.locator("textarea, .CodeMirror textarea, [role='textbox']").first
            editor.wait_for(state="visible", timeout=5000)
            editor.click()
            page.keyboard.press("Control+a")
            page.wait_for_timeout(200)

            # Set clipboard via browser API, then Ctrl+V
            page.evaluate(
                "text => navigator.clipboard.writeText(text)",
                manifest_yaml
            )
            page.keyboard.press("Control+v")
            page.wait_for_timeout(500)

            # Verify something was pasted by checking editor isn't empty
            content = editor.input_value() if editor.evaluate("el => el.tagName") == "TEXTAREA" else ""
            if content and len(content) > 50:
                pasted = True
            else:
                # Fallback: try fill() for plain textareas
                editor.fill(manifest_yaml)
                pasted = True

            if pasted:
                success("Pasted manifest YAML")
        except Exception:
            pass

        if not pasted:
            warn("Couldn't auto-paste the manifest.")
            _copy_to_clipboard(manifest_yaml)
            wait_msg("The manifest has been copied to your clipboard (Ctrl+V to paste).")
            wait_msg("If clipboard didn't work, the manifest is printed below.")
            print()
            for line in manifest_yaml.strip().split('\n'):
                print(f"        {line}")
            print()

        wait_msg("Review the manifest, then click Next → Create.")
        input(f"      {bold('→ Press ENTER after the app is created...')}")

        page.wait_for_timeout(2000)

        # ── Step: Generate App-Level Token ───────────────────────────
        step(7, "Generating App-Level Token (for Socket Mode)...")

        # We should now be on the Basic Information page
        current_url = page.url
        if "/apps/" in current_url:
            app_id_match = re.search(r'/apps/([A-Z0-9]+)', current_url)
            if app_id_match:
                app_id = app_id_match.group(1)
                success(f"App created: {app_id}")

        try:
            gen_token_btn = page.locator("text=Generate Token and Scopes").first
            gen_token_btn.wait_for(state="visible", timeout=5000)
            gen_token_btn.click()
            page.wait_for_timeout(1500)

            # Fill token name
            token_name_input = page.locator("input[placeholder*='oken']").first
            if not token_name_input.is_visible(timeout=2000):
                token_name_input = page.locator("dialog input[type='text'], .modal input[type='text']").first
            token_name_input.fill("socket-mode")
            page.wait_for_timeout(500)

            # Add connections:write scope
            try:
                scope_dropdown = page.locator("text=Add Scope").first
                scope_dropdown.click()
                page.wait_for_timeout(500)
                connections_option = page.locator("text=connections:write").first
                connections_option.click()
                page.wait_for_timeout(500)
            except Exception:
                warn("Couldn't auto-select scope.")
                wait_msg("Please add 'connections:write' scope manually.")

            # Click Generate
            try:
                generate_btn = page.locator("button:has-text('Generate')").first
                generate_btn.click()
                page.wait_for_timeout(2000)
            except Exception:
                pass

            # Try to find the generated token
            try:
                token_el = page.locator("text=/xapp-[a-zA-Z0-9-]+/").first
                token_el.wait_for(state="visible", timeout=5000)
                token_text = token_el.text_content()
                xapp_match = re.search(r'(xapp-\S+)', token_text)
                if xapp_match:
                    tokens["app_token"] = xapp_match.group(1)
                    success(f"App Token: {tokens['app_token'][:20]}...")
            except Exception:
                pass

        except Exception:
            warn("Couldn't auto-generate token.")

        if not tokens["app_token"]:
            wait_msg("Please generate an App-Level Token manually:")
            wait_msg("  1. Scroll to 'App-Level Tokens' on this page")
            wait_msg("  2. Click 'Generate Token and Scopes'")
            wait_msg("  3. Name it 'socket-mode'")
            wait_msg("  4. Add scope: connections:write")
            wait_msg("  5. Click Generate and copy the xapp-... token")
            tokens["app_token"] = prompt("Paste the App-Level Token (xapp-...)")

        # ── Step: Install to Workspace & Get Bot Token ───────────────
        step(8, "Installing app to workspace...")

        try:
            install_link = page.locator("a:has-text('Install App')").first
            install_link.wait_for(state="visible", timeout=3000)
            install_link.click()
            page.wait_for_timeout(2000)
        except Exception:
            try:
                page.goto(re.sub(r'/[^/]*$', '/install-on-team', page.url))
                page.wait_for_timeout(2000)
            except Exception:
                pass

        # Click Install to Workspace button
        try:
            install_btn = page.locator("button:has-text('Install to'), a:has-text('Install to')").first
            install_btn.wait_for(state="visible", timeout=3000)
            install_btn.click()
            page.wait_for_timeout(3000)
        except Exception:
            pass

        # Click Allow
        try:
            allow_btn = page.locator("button:has-text('Allow')").first
            if allow_btn.is_visible(timeout=3000):
                allow_btn.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

        # Try to find Bot Token
        try:
            token_el = page.locator("text=/xoxb-[a-zA-Z0-9-]+/").first
            if token_el.is_visible(timeout=5000):
                token_text = token_el.text_content()
                xoxb_match = re.search(r'(xoxb-\S+)', token_text)
                if xoxb_match:
                    tokens["bot_token"] = xoxb_match.group(1)
                    success(f"Bot Token: {tokens['bot_token'][:20]}...")
        except Exception:
            pass

        # Navigate to OAuth page for token
        if not tokens["bot_token"]:
            try:
                oauth_link = page.locator("a:has-text('OAuth')").first
                oauth_link.click()
                page.wait_for_timeout(2000)

                token_el = page.locator("text=/xoxb-[a-zA-Z0-9-]+/").first
                if token_el.is_visible(timeout=5000):
                    token_text = token_el.text_content()
                    xoxb_match = re.search(r'(xoxb-\S+)', token_text)
                    if xoxb_match:
                        tokens["bot_token"] = xoxb_match.group(1)
                        success(f"Bot Token: {tokens['bot_token'][:20]}...")
            except Exception:
                pass

        if not tokens["bot_token"]:
            wait_msg("Please copy the Bot User OAuth Token manually:")
            wait_msg("  Go to OAuth & Permissions → Bot User OAuth Token")
            tokens["bot_token"] = prompt("Paste the Bot Token (xoxb-...)")

        # ── Done with browser ────────────────────────────────────────
        wait_msg("You can close the browser now (or leave it open).")
        input(f"      {bold('→ Press ENTER to continue...')}")

        try:
            browser.close()
        except Exception:
            pass

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
    check_deps()
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
    manifest_yaml = generate_manifest(bot_name, bot_name, description)
    success("Manifest ready")
    print()
    for line in manifest_yaml.strip().split('\n')[:8]:
        print(f"      {dim(line)}")
    print(f"      {dim('...')}")
    print()

    tokens = run_browser_setup(manifest_yaml, agent_slug)

    if not tokens.get("bot_token") or not tokens.get("app_token"):
        fail("Missing tokens. Please re-run setup.")

    step(9, "Configuring environment")
    channel_id = prompt("Default channel ID (right-click channel → Copy link → ID at end)", "")

    env_path = write_env_file(agent_slug, tokens, channel_id, claude_path)

    step(10, "Done!")
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
