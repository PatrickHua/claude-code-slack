# Manager-Agent Architecture

A design for always-responsive, multi-task Slack bots powered by Claude Code.

---

## The Problem

Today's bot is **single-threaded per session**: when Claude is working on a task (running tools, reading files, searching the web), the user waits. There's no way to:

- Chat with the bot while it works on something
- Run multiple tasks in parallel
- Have a task pause and ask the user a question
- Cancel a long-running task mid-flight

The interactive Claude Code CLI solves this with background tasks, but `claude -p` (our backend) is one-shot and blocking.

---

## Core Idea

Split the system into three layers:

```
┌─────────────────────────────────────┐
│            HUMAN (Slack)            │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     MANAGER (fast, always free)     │  ← responds in ~1-2 seconds
│                                     │
│  • Pure reasoning, no tools         │
│  • Reads task registry each turn    │
│  • Decides: talk / spawn / kill /   │
│    relay info / check status        │
└──┬──────────┬──────────┬────────────┘
   │          │          │
┌──▼───┐  ┌──▼───┐  ┌──▼───┐
│ W #1 │  │ W #2 │  │ W #3 │          ← background workers
│      │  │      │  │      │
│ full │  │ full │  │ full │
│tools │  │tools │  │tools │
└──────┘  └──────┘  └──────┘
```

### What is the "Python bot" vs the "Manager"?

The **Python bot** is the process — the `slack-bot.py` script that connects to Slack, receives events, manages threads, and posts replies. It's infrastructure. It never reasons.

The **Manager** is an LLM call that the Python bot makes. Every time a Slack message arrives, the bot calls `claude -p` with a special manager prompt. The manager's job is pure reasoning: understand the human, look at the task list, decide what to do. It returns a structured JSON action. The bot executes that action (post a message, start a thread, kill a process).

Think of it this way:
- **Python bot** = the nervous system (routes signals, moves muscles)
- **Manager** = the brain (understands, decides, delegates)
- **Workers** = the hands (do the actual work)

The manager is fast because it has **no tools and a 1-turn limit**. It can't browse the web, read files, or write code. It only thinks and returns a JSON command. This guarantees it completes in ~1-2 seconds.

---

## The Manager's Dynamic Prompt

Each time the human sends a message, the bot builds a prompt that includes live task state:

```
You are the manager for {bot_name}. You coordinate between the human and
background worker agents. You NEVER do work yourself — you delegate.

Your conversation history with the human is below. Workers run separately.

═══ ACTIVE TASKS ═══
  #1 [running 3m12s] "Research quantum error correction"
     last_status: "Found 12 papers, reading abstracts..."
  #2 [BLOCKED 45s]   "Refactor auth module"
     needs_input: "Which library do you prefer: jose or authlib?"
  #3 [done 2m ago]   "Summarize PR #42"
     result_file: /tmp/tasks/3-result.md

═══ ACTIONS ═══
Respond with a JSON array of actions:

  {"action": "talk", "message": "..."}
    Reply to the human.

  {"action": "spawn", "task_name": "...", "prompt": "...", "context_k": 5}
    Start a background task. context_k = number of recent conversation
    turns to forward as context (so you don't have to re-explain).

  {"action": "kill", "id": 2}
    Cancel a running task.

  {"action": "reply_to", "id": 2, "message": "..."}
    Send the human's answer to a blocked worker.

  {"action": "read_result", "id": 3}
    Read and relay a completed task's output to the human.
```

### Example exchange

Human says: *"use authlib. also how's the quantum research? and can you start reviewing my PR #58?"*

Manager returns:
```json
[
  {"action": "reply_to", "id": 2, "message": "The human says to use authlib."},
  {"action": "talk", "message": "Task #1 (quantum research) is 3 minutes in — it's found 12 papers and is reading through abstracts. I'll post results when it's done.\n\nI'll kick off a review of PR #58 now."},
  {"action": "spawn", "task_name": "review-pr-58", "prompt": "Review pull request #58 for code quality, bugs, and security issues.", "context_k": 0}
]
```

Bot executes all three: feeds authlib answer to worker #2 via `--resume`, posts the status message to Slack, spawns worker #4 in a new thread. Total wall time: ~2 seconds.

---

## Context Forwarding (the `context_k` Mechanism)

One of the biggest inefficiencies in delegation: the manager has to *re-explain* everything to the worker. If the human just spent 10 messages describing what they want, the manager would need to summarize all of that into the spawn prompt — burning tokens and losing nuance.

**Solution: forward the last K conversation turns directly.**

When the manager emits `{"action": "spawn", "prompt": "...", "context_k": 5}`, the bot:

1. Takes the last 5 human↔manager exchanges from the conversation history
2. Prepends them to the worker's prompt as context
3. The worker sees the original human words, not the manager's summary

```
Worker prompt (auto-constructed by bot):
═══════════════════════════════════════
CONTEXT (forwarded from human conversation):

[Human]: I have a FastAPI app with JWT auth but the token refresh
         is broken. Sometimes users get logged out mid-session.
[Manager]: I'll look into that.
[Human]: The refresh endpoint is in auth/routes.py. I think the
         issue is with the expiry check.
[Manager]: Got it, spawning a task to investigate.

═══════════════════════════════════════
YOUR TASK: Debug the JWT token refresh issue in auth/routes.py.
Focus on the expiry check logic.
═══════════════════════════════════════
```

The worker gets the full context without the manager spending tokens to rephrase it. The manager just says "investigate this" and sets `context_k: 3` to forward the relevant conversation window.

### Why this matters

- **Zero-cost delegation**: Manager doesn't produce tokens to explain — it references history
- **No information loss**: Worker sees exact human words, not a summary
- **Adjustable window**: `context_k: 0` for self-contained tasks, `context_k: 10` for complex context-heavy ones
- **The manager learns to set K**: Over time, the manager figures out how much context each type of task needs

---

## Worker → Manager Communication

Workers need to report back. Since workers are `claude -p` calls that run to completion, communication happens at turn boundaries.

### Status updates (periodic)

Workers don't stream status natively. But we can approximate it:

**Option A: Multi-turn workers with checkpointing**

Instead of one long `claude -p` call, the bot runs the worker in a loop:

```python
while task.status == "running":
    response, session_id = run_claude(
        "Continue working. If you're done, start with DONE:. "
        "If you need input, start with BLOCKED:. "
        "Otherwise start with STATUS: and a one-line progress update, "
        "then keep working.",
        session_id=task.session_id,
        max_turns=3  # work for a few turns, then checkpoint
    )

    if response.startswith("DONE:"):
        task.status = "done"
        task.result = response[5:]
        post_to_slack(f"✓ Task #{task.id} done.")
    elif response.startswith("BLOCKED:"):
        task.status = "blocked"
        task.needs_input = response[8:]
        post_to_slack(f"⏸ Task #{task.id} asks: {task.needs_input}")
    else:
        # STATUS: update, task continues
        task.last_status = response.split("\n")[0]
        # Loop continues → next claude -p --resume call
```

This gives us periodic checkpoints where we can:
- Update the task registry (which the manager reads)
- Post progress to Slack
- Check if the human wants to cancel
- Inject new context if the human provided more info

**Option B: Completion-only reporting**

Simpler: just let the worker run to completion and report when done. No intermediate status. Fine for tasks under ~2 minutes.

### Result delivery

When a worker finishes, the bot can either:
1. **Post directly**: Send the result to Slack immediately
2. **Store and notify**: Write result to a file, tell the manager "task #3 is done", let the manager decide how to present it
3. **Manager summarizes**: Feed the result back to the manager for a concise summary (useful if the raw output is verbose)

Option 2 is cleanest — the manager stays in control of all communication with the human.

---

## Task Lifecycle

```
SPAWNED → RUNNING → DONE
                  → BLOCKED → (human answers) → RUNNING → ...
                  → CANCELLED (by human or manager)
                  → FAILED (error/timeout)
```

### Task state (in-memory dict)

```python
tasks = {
    1: {
        "name": "research-quantum",
        "status": "running",           # running|blocked|done|failed|cancelled
        "prompt": "Research quantum...",
        "session_id": "abc-123",        # claude --resume ID
        "thread": <Thread>,             # Python thread handle
        "started_at": 1708900000,
        "last_status": "Found 12 papers...",
        "needs_input": None,            # set when BLOCKED
        "result": None,                 # set when DONE
        "result_file": None,            # for large outputs
    }
}
```

---

## Implementation Phases

### Phase 1: Background tasks (no manager LLM)

Skip the LLM manager entirely. Use bang commands:

- `!spawn <prompt>` → starts background worker
- `!status` → lists all tasks
- `!kill <id>` → cancels a task
- Normal messages → go to the current session (existing behavior)

This gets 80% of the value with minimal changes. The bot is always responsive because workers run in threads.

### Phase 2: LLM manager with triage

Replace the bang commands with a fast LLM call that triages:
- Quick questions → answer directly (1-turn, no tools)
- Complex tasks → spawn workers
- Status checks → read task registry
- Ambiguous → ask the human

This is where `context_k` forwarding kicks in.

### Phase 3: Worker checkpointing and feedback loop

Add the multi-turn worker loop with STATUS/DONE/BLOCKED parsing. Workers can now:
- Report progress
- Ask questions
- Be resumed with new context

### Phase 4: Worker-to-worker coordination

Workers can request the manager to spawn sibling tasks. The manager sees all worker outputs and can synthesize across them. Example: researcher finds something relevant to the coder's task → manager relays the finding.

---

## Open Questions

1. **Session isolation**: Should manager and workers share a claude session, or be fully independent? Independent is safer (no context pollution) but can't reference each other's work natively.

2. **Token budget**: The manager prompt grows with task history. Need a compaction strategy — archive completed tasks, summarize old status updates.

3. **Slack threading**: Should each task get its own Slack thread? Makes the UI cleaner — task progress and results appear in their respective threads.

4. **Persistence**: If the bot restarts, task state is lost. Should we persist the task registry to disk (like we do with sessions)?

5. **Worker model selection**: Cheap model (Haiku/Sonnet) for grunt work, expensive model (Opus) for complex reasoning? The manager could decide based on task complexity.

6. **Parallel workers per session**: How many concurrent workers should we allow? Need to consider API rate limits and server resources.

---

## Comparison with Alternatives

| Approach | Always responsive | Background tasks | Worker feedback | Context forwarding | Complexity |
|---|---|---|---|---|---|
| Current (`claude -p` blocking) | No | No | N/A | N/A | Simple |
| SDK with native subagents | No (blocks during query) | Yes (parallel subagents) | No (subagents can't call back) | No | Medium |
| **This architecture** | **Yes** | **Yes** | **Yes (checkpoint loop)** | **Yes (context_k)** | Medium |
| Full interactive CLI replica | Yes | Yes | Yes | Yes | Very high |

The manager-agent pattern gives us most of the interactive CLI's power without rewriting the event loop. The trade-off is that worker feedback is at checkpoint boundaries (every few turns) rather than truly real-time — but for a Slack bot where humans check back every few minutes anyway, that's perfectly fine.
