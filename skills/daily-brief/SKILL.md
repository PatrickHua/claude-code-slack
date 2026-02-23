---
name: daily-brief
description: Send automated morning briefing via Slack with weather, news, and motivational quotes.
---

# Daily Brief

Send a daily morning briefing to Slack.

## Workflow

1. Confirm today's date using `date` command
2. Gather content:
   - Weather via wttr.in (no API key needed)
   - News headlines via WebSearch
   - Motivational quotes via WebSearch (rotated by day of week)
3. Format as a Slack message
4. Send via slack-sender skill

## Quote Rotation

| Day | Theme | Search Query |
|-----|-------|--------------|
| Mon | Motivation | "motivational quote monday" |
| Tue | Growth | "personal growth quote" |
| Wed | Gratitude | "gratitude quote" |
| Thu | Productivity | "productivity quote" |
| Fri | Wisdom | "wisdom quote friday" |
| Sat | Rest | "rest and relaxation quote" |
| Sun | Reflection | "reflection quote sunday" |

## Message Format

```
:sunny: Daily Briefing - {Day}, {Month} {Date}

:cloud: {weather_output}

:newspaper: Headlines:
- {headline_1}
- {headline_2}
- {headline_3}

:sparkles: "{quote}"
— {attribution}

Have a great day! :rocket:
```

## Scheduling

Use cron (Linux) or launchd (macOS) to run daily:

```bash
# Run at 7:00 AM daily
0 7 * * * claude -p "Run the daily-brief skill" --allowedTools Read,WebSearch,Bash,Skill
```
