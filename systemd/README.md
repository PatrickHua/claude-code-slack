# Running as a systemd Service (Linux)

## Setup

### 1. Edit the service file

Update `claude-slack-bot.service` with your paths:
- `WorkingDirectory` - path to this repo
- `ExecStart` - path to your Python and slack-bot.py
- `User` - your username

### 2. Install the service

```bash
# Copy service file
sudo cp claude-slack-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start
sudo systemctl enable claude-slack-bot
sudo systemctl start claude-slack-bot
```

### 3. Check status

```bash
sudo systemctl status claude-slack-bot
```

### 4. View logs

```bash
journalctl -u claude-slack-bot -f
```

## Common Commands

```bash
# Start
sudo systemctl start claude-slack-bot

# Stop
sudo systemctl stop claude-slack-bot

# Restart
sudo systemctl restart claude-slack-bot

# Disable auto-start
sudo systemctl disable claude-slack-bot
```

## Daily Brief (cron)

For scheduled skills like daily briefings, use cron:

```bash
crontab -e
```

Add:
```
0 7 * * * cd /path/to/workspace && claude -p "Run the daily-brief skill" --allowedTools Read,WebSearch,Bash,Skill >> /tmp/daily-brief.log 2>&1
```
