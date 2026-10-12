# WorkBench Tools

Your workspace contains CLI scripts to interact with workplace data.
All scripts require: `WB_WORKSPACE` env var set to this workspace directory.

Run them with: `WB_WORKSPACE=$(pwd) python3 wb-<tool>.py <command> [args]`

---

## wb-calendar.py — Calendar

```
WB_WORKSPACE=$(pwd) python3 wb-calendar.py list                                          # list all events
WB_WORKSPACE=$(pwd) python3 wb-calendar.py list --date 2026-12-13                       # filter by date (YYYY-MM-DD)
WB_WORKSPACE=$(pwd) python3 wb-calendar.py list --date 2026-12                          # filter by month (YYYY-MM)
WB_WORKSPACE=$(pwd) python3 wb-calendar.py list --start "2026-12-13 00:00:00"           # filter from datetime
WB_WORKSPACE=$(pwd) python3 wb-calendar.py list --start "2026-12-13 00:00:00" --end "2026-12-13 23:59:59"  # date range
WB_WORKSPACE=$(pwd) python3 wb-calendar.py create --name <name> --participant <email> --start "YYYY-MM-DD HH:MM:SS" --duration <mins>
WB_WORKSPACE=$(pwd) python3 wb-calendar.py update --id <event_id> --field <field> --value <value>
WB_WORKSPACE=$(pwd) python3 wb-calendar.py delete --id <event_id>
```

## wb-email.py — Email

```
WB_WORKSPACE=$(pwd) python3 wb-email.py list                                             # list emails in inbox
WB_WORKSPACE=$(pwd) python3 wb-email.py read --id <email_id>                             # read full email content
WB_WORKSPACE=$(pwd) python3 wb-email.py send --to <email> --subject <subject> --body <body>   # compose and send a NEW email
WB_WORKSPACE=$(pwd) python3 wb-email.py reply --id <email_id> --body <body>              # reply to an existing email (use this, not send)
WB_WORKSPACE=$(pwd) python3 wb-email.py forward --id <email_id> --to <email>             # forward an existing email to someone (use this, not send)
WB_WORKSPACE=$(pwd) python3 wb-email.py delete --id <email_id>
```

## wb-crm.py — CRM

```
WB_WORKSPACE=$(pwd) python3 wb-crm.py list
WB_WORKSPACE=$(pwd) python3 wb-crm.py get --id <customer_id>
WB_WORKSPACE=$(pwd) python3 wb-crm.py update --id <customer_id> --field <field> --value <value>
```

## wb-project.py — Project Tasks

```
WB_WORKSPACE=$(pwd) python3 wb-project.py list
WB_WORKSPACE=$(pwd) python3 wb-project.py create --name <name> --assignee <email> --due <date> --status <status>
WB_WORKSPACE=$(pwd) python3 wb-project.py update --id <task_id> --field <field> --value <value>
WB_WORKSPACE=$(pwd) python3 wb-project.py delete --id <task_id>
```

## wb-analytics.py — Analytics

```
WB_WORKSPACE=$(pwd) python3 wb-analytics.py metrics
WB_WORKSPACE=$(pwd) python3 wb-analytics.py query --metric <metric> [--from YYYY-MM-DD] [--to YYYY-MM-DD]
WB_WORKSPACE=$(pwd) python3 wb-analytics.py plot --metric <metric> --type <bar|line|scatter|histogram> [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

Available metrics: `total_visits`, `user_engaged`, `session_duration_seconds`,
`visits_social_media`, `visits_search_engine`, `visits_referral`, `visits_direct`

Output file: `plots/{from}_{to}_{metric}_{type}.png`

---

**Always use `WB_WORKSPACE=$(pwd)` prefix when running these scripts.**

**Placeholder syntax:** In the examples above, `<name>`, `<event_id>`, `<email_id>`, etc. are placeholders — replace them with the actual value, with no surrounding brackets of any kind. Example: `--id 00000008` not `--id [00000008]` or `--id <00000008>`.
