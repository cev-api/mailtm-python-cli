## Mail.tm CLI (Python)

A simple Python CLI to interact with the Mail.tm temporary email service: create accounts, list domains, fetch and manage messages, and more. It uses the public Mail.tm API.

### Features
- Create temp mail accounts and log in
- List domains or fetch a specific domain
- Inspect your account (via /me) or fetch by id
- Delete your account (resolve id via /me or delete by explicit id)
- List, read, mark seen, delete messages
- Save raw message source (.eml) and download attachments

### Requirements
- Python 3.8+
- `requests` library

Install dependency:
```bash
pip install requests
```

### Help!
```bash
# Show help and examples
python mailtm.py --help
```

### Commands and examples

#### Login
```bash
python mailtm.py login --email you@domain --password 'pw'
```

#### Domains
```bash
# List domains (paged)
python mailtm.py domains --page 1

# Get a single domain by id
python mailtm.py domain <DOMAIN_ID>
```

#### Accounts
```bash
# Create account (random local-part)
python mailtm.py account create --random --password 'pw'

# Create account (explicit local and domain)
python mailtm.py account create --local myuser --domain example.mail.tm --password 'pw'

# Show current account (/me)
python mailtm.py account me --email you@domain --password 'pw'

# Get account by id
python mailtm.py account get <ACCOUNT_ID> --email you@domain --password 'pw'

# Delete current account (id resolved via /me)
python mailtm.py account delete --email you@domain --password 'pw'

# Delete by explicit account id
python mailtm.py account delete-id <ACCOUNT_ID> --email you@domain --password 'pw'
```

#### Messages
```bash
# List messages
python mailtm.py messages list --email you@domain --password 'pw' --page 1

# Read a message (optionally mark as seen)
python mailtm.py messages read <MSG_ID> --email you@domain --password 'pw' --mark-seen

# Read the newest message (optionally mark as seen)
python mailtm.py messages latest --email you@domain --password 'pw' --mark-seen

# Delete a message
python mailtm.py messages delete <MSG_ID> --email you@domain --password 'pw'

# Mark a message as seen
python mailtm.py messages mark-seen <MSG_ID> --email you@domain --password 'pw'

# Save raw message source (.eml)
python mailtm.py messages save-source <MSG_ID> --out msg.eml --email you@domain --password 'pw'

# Download all attachments of a message
python mailtm.py messages save-atts <MSG_ID> --dir ./downloads --email you@domain --password 'pw'
```

### Notes
- Most endpoints require authentication; create an account first and then log in to obtain a bearer token (handled automatically by the CLI when `--email`/`--password` are provided).
- API rate limit: 8 QPS per IP.

### Reference
- Mail.tm API documentation: [docs.mail.tm](https://docs.mail.tm/)


