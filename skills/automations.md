---
name: automations
description: Run natural-language cron automations
when_to_use: When the user asks to create, list, or delete a recurring automation job, or when an automation is due and its result should be reported
tools: ["create_automation", "list_automations", "delete_automation"]
revision: 1
---

# Cron automations

The backend supports user-defined recurring jobs expressed as natural-language cron expressions. Automations are hidden behind `use_skill("automations")` (progressive disclosure, ADR-009) — they do not appear in the default tool-schema payload.

## Workflow

### Create an automation

Call `create_automation` with a human-readable name, a standard cron expression, and the action to execute when the cron fires.

**Example:** `create_automation(name="Daily digest", cron="0 9 * * *", action="send_sms")`

This creates an automation that will fire at 9am daily, executing the `send_sms` action.

### List automations

Call `list_automations` to see all enabled automations (default), or `list_automations(enabled_only=False)` to see all including disabled.

### Delete an automation

Call `delete_automation(automation_id=<id>)` where the id is returned by `create_automation`. This disables and removes the automation.

### Scheduler firing

The background scheduler (app/scheduler.py) polls every 30 seconds for due automations using `croniter`. When an automation is due:

1. The scheduler executes the automation's action via the tool registry
2. The result is FCM-pushed to all registered device tokens
3. The automation is disabled to avoid repeated triggers

The cron expression format follows standard cron (e.g., `0 9 * * *` for 9am daily, `0 * * * *` for every hour). See the test file for more examples.

## When to use

- `use_skill("automations")` when the user asks to set up a recurring job
- When an automation is due and the user wants to know the result via FCM push
- To manage (create/list/delete) user-defined recurring tasks