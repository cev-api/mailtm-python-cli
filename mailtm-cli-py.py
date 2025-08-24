#!/usr/bin/env python3

# Mail.tm CLI covering accounts, domains, and messages by CevAPI
# Uses https://api.mail.tm as the fixed API base.

import argparse
import sys
import os
import time
import json
import re
import random
import string
from typing import Any, Dict, List
from html import unescape

try:
    import requests
except ImportError:
    print("This script requires the 'requests' package. Install with:\n  pip install requests")
    sys.exit(1)

API_BASE = "https://api.mail.tm"


# --------------------------
# Helpers
# --------------------------

def _simplify_html(html_parts):
    if not html_parts:
        return ""
    html = "\n\n".join([part for part in html_parts if isinstance(part, str)])
    html = unescape(html)
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|h\d|li|tr|table|ul|ol)>", "\n", html)
    html = re.sub(r"(?s)<.*?>", "", html)
    html = re.sub(r"[ \t]+\n", "\n", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _normalize_collection(coll: Any) -> Dict[str, Any]:
    if isinstance(coll, list):
        return {"hydra:member": coll, "hydra:totalItems": len(coll)}
    return coll if isinstance(coll, dict) else {"hydra:member": [], "hydra:totalItems": 0}


def _format_address(addr: Any) -> str:
    if isinstance(addr, dict):
        name = addr.get("name") or ""
        email = addr.get("address") or ""
        if name and email:
            return f"{name} <{email}>"
        return email or name
    if isinstance(addr, str):
        return addr
    return ""


def _format_address_list(addrs: Any) -> str:
    if addrs is None:
        return ""
    if isinstance(addrs, dict):
        addrs = [addrs]
    if isinstance(addrs, str):
        addrs = [addrs]
    if isinstance(addrs, list):
        parts = []
        for a in addrs:
            s = _format_address(a)
            if s:
                parts.append(s)
        return ", ".join(parts)
    return ""


def _sort_desc_by_created(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda m: (m.get("createdAt") or ""), reverse=True)


def _rand_local_part(n=10) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


# --------------------------
# API Client
# --------------------------

class MailTMClient:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._token = None
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/ld+json, application/json;q=0.9",
            "User-Agent": "mailtm-client/2.0 (+https://mail.tm)"
        })

    def _url(self, path: str) -> str:
        return f"{API_BASE}{path}"

    def _auth_headers(self) -> dict:
        if not self._token:
            raise RuntimeError("Not authenticated. Call login() first.")
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, path: str, auth: bool = False, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout
        url = self._url(path)
        if auth:
            hdrs = kwargs.pop("headers", {})
            hdrs.update(self._auth_headers())
            kwargs["headers"] = hdrs
        resp = self._session.request(method.upper(), url, **kwargs)
        if not resp.ok:
            msg = f"{method} {path} -> HTTP {resp.status_code}"
            try:
                data = resp.json()
                msg += f" | {json.dumps(data, ensure_ascii=False)}"
            except Exception:
                msg += f" | {resp.text[:300]}"
            raise requests.HTTPError(msg, response=resp)
        if resp.status_code == 204:
            return None
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype or "application/ld+json" in ctype:
            try:
                return resp.json()
            except Exception:
                return resp.text
        return resp.text

    # auth & accounts
    def login(self, address: str, password: str) -> Dict[str, Any]:
        payload = {"address": address, "password": password}
        data = self._request("POST", "/token", json=payload)
        token = data.get("token")
        if not token:
            raise RuntimeError("Login failed: no token in response.")
        self._token = token
        self._session.headers.update(self._auth_headers())
        return data

    def me(self) -> Dict[str, Any]:
        return self._request("GET", "/me", auth=True)

    def get_account(self, account_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/accounts/{account_id}", auth=True)

    def create_account(self, address: str, password: str) -> Dict[str, Any]:
        payload = {"address": address, "password": password}
        return self._request("POST", "/accounts", json=payload)

    def delete_account(self, account_id: str) -> None:
        self._request("DELETE", f"/accounts/{account_id}", auth=True)

    # domains
    def list_domains(self, page: int = 1) -> Dict[str, Any]:
        coll = self._request("GET", f"/domains?page={page}")
        return _normalize_collection(coll)

    def get_domain(self, domain_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/domains/{domain_id}")

    def pick_domain(self) -> str:
        coll = self.list_domains(page=1)
        items = coll.get("hydra:member", [])
        if not items:
            raise RuntimeError("No domains available.")
        for d in items:
            if d.get("isActive", True):
                return d.get("domain") or d.get("name") or ""
        return items[0].get("domain") or items[0].get("name") or ""

    # messages
    def list_messages(self, page: int = 1) -> Dict[str, Any]:
        coll = self._request("GET", f"/messages?page={page}", auth=True)
        return _normalize_collection(coll)

    def get_message(self, msg_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/messages/{msg_id}", auth=True)

    def delete_message(self, msg_id: str) -> None:
        self._request("DELETE", f"/messages/{msg_id}", auth=True)

    def mark_seen(self, msg_id: str) -> Dict[str, Any]:
        payload = {"seen": True}
        return self._request("PATCH", f"/messages/{msg_id}", json=payload, auth=True)

    def get_message_source(self, msg_id: str) -> bytes:
        # Prefer documented /sources/{id} endpoint; keep backward-compatible fallback
        src_url = self._url(f"/sources/{msg_id}")
        r = self._session.get(src_url, headers=self._auth_headers(), timeout=self.timeout)
        if r.ok:
            # API returns JSON with 'data' base64 or raw string; but also supports downloadUrl
            ctype = r.headers.get("Content-Type", "")
            if "application/json" in ctype or "application/ld+json" in ctype:
                try:
                    data = r.json()
                    payload = data.get("data")
                    if isinstance(payload, str):
                        return payload.encode("utf-8", errors="ignore")
                except Exception:
                    pass
            return r.content
        # Fallback legacy path
        legacy_url = self._url(f"/messages/{msg_id}/source")
        r2 = self._session.get(legacy_url, headers=self._auth_headers(), timeout=self.timeout)
        if not r2.ok:
            raise requests.HTTPError(
                f"GET /sources/{msg_id} -> {r.status_code}; fallback /messages/{msg_id}/source -> {r2.status_code} | {r2.text[:200]}"
            )
        return r2.content

    def list_attachments(self, msg: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [a for a in (msg.get("attachments") or []) if isinstance(a, dict)]

    def download_attachment(self, msg_id: str, attachment_id: str) -> bytes:
        # Try documented approach via message details' downloadUrl first when available
        # If not available, fall back to legacy path
        url = self._url(f"/messages/{msg_id}/attachments/{attachment_id}")
        r = self._session.get(url, headers=self._auth_headers(), timeout=self.timeout)
        if not r.ok:
            raise requests.HTTPError(
                f"GET /messages/{msg_id}/attachments/{attachment_id} -> {r.status_code} | {r.text[:200]}"
            )
        return r.content


# --------------------------
# Printers
# --------------------------

def print_account_info(me):
    print("Account")
    print("-------")
    print(f"ID:       {me.get('id')}")
    print(f"Address:  {me.get('address')}")
    print(f"Used:     {me.get('used')}")
    print(f"Quota:    {me.get('quota')}")
    print(f"Disabled: {me.get('isDisabled')}")
    print(f"Deleted:  {me.get('isDeleted')}")
    print()


def print_domains(coll):
    items = coll.get("hydra:member", [])
    total = coll.get("hydra:totalItems", len(items))
    print(f"Domains (showing {len(items)} of ~{total})")
    print("--------------------------------------------------------------")
    if not items:
        print("(none)")
        return
    for d in items:
        dom = d.get("domain") or d.get("name") or ""
        is_active = d.get("isActive", True)
        created = d.get("createdAt") or ""
        print(f"- {dom}  active={is_active}  created={created}")
    print()


def print_list(coll):
    items = _sort_desc_by_created(coll.get("hydra:member", []))
    total = coll.get("hydra:totalItems", len(items))
    print(f"Inbox (showing {len(items)} of ~{total})")
    print("--------------------------------------------------------------")
    if not items:
        print("(empty)")
        return
    for it in items:
        created = it.get("createdAt")
        subj = it.get("subject") or "(no subject)"
        mid = it.get("id")
        intro = it.get("intro") or ""
        seen = "✓" if it.get("seen") else " "
        frm_str = _format_address(it.get("from"))
        print(f"[{seen}] {created}  {subj}")
        print(f"      From: {frm_str}")
        print(f"      ID:   {mid}")
        if intro:
            print(f"      Intro: {intro[:120].replace('\\n',' ')}{'…' if len(intro) > 120 else ''}")
        print()


def print_message(full):
    print("Message")
    print("-------")
    print(f"ID:       {full.get('id')}")
    print(f"Date:     {full.get('createdAt')}")
    print(f"From:     {_format_address(full.get('from'))}")
    tos_raw = full.get("to") or full.get("recipients")
    print(f"To:       {_format_address_list(tos_raw)}")
    print(f"Subject:  {full.get('subject') or '(no subject)'}")
    print(f"Seen:     {full.get('seen')}")
    print(f"Size:     {full.get('size')}")
    print(f"HasAtts:  {full.get('hasAttachments')}")
    print()
    body_text = full.get("text")
    if isinstance(body_text, str) and body_text.strip():
        print("Text Body")
        print("---------")
        print(body_text.strip())
        print()
    else:
        html_parts = full.get("html") or []
        if html_parts:
            simplified = _simplify_html(html_parts)
            if simplified:
                print("HTML Body (simplified)")
                print("----------------------")
                print(simplified)
                print()
            else:
                print("(No body content)")
        else:
            print("(No body content)")
    if full.get("hasAttachments"):
        for a in full.get("attachments") or []:
            if isinstance(a, dict):
                print(f"- id={a.get('id')}  name={a.get('filename')}  type={a.get('contentType')}  size={a.get('size')}")
    print()


# --------------------------
# CLI
# --------------------------

def build_parser():
    app_desc = (
        "Mail.tm CLI\n"
        "\n"
        "Commands cover accounts, domains, and messages.\n"
        "Examples:\n"
        "  # Login and show current account (/me)\n"
        "  mailtm.py login --email you@domain --password 'pw'\n"
        "\n"
        "  # Domains\n"
        "  mailtm.py domains --page 1\n"
        "  mailtm.py domain <DOMAIN_ID>\n"
        "\n"
        "  # Accounts\n"
        "  mailtm.py account create --random --password 'pw'\n"
        "  mailtm.py account create --local myuser --domain example.mail.tm --password 'pw'\n"
        "  mailtm.py account me --email you@domain --password 'pw'\n"
        "  mailtm.py account get <ACCOUNT_ID> --email you@domain --password 'pw'\n"
        "  mailtm.py account delete --email you@domain --password 'pw'\n"
        "  mailtm.py account delete-id <ACCOUNT_ID> --email you@domain --password 'pw'\n"
        "\n"
        "  # Messages\n"
        "  mailtm.py messages list --email you@domain --password 'pw' --page 1\n"
        "  mailtm.py messages read <MSG_ID> --email you@domain --password 'pw' --mark-seen\n"
        "  mailtm.py messages latest --email you@domain --password 'pw' --mark-seen\n"
        "  mailtm.py messages delete <MSG_ID> --email you@domain --password 'pw'\n"
        "  mailtm.py messages mark-seen <MSG_ID> --email you@domain --password 'pw'\n"
        "  mailtm.py messages save-source <MSG_ID> --out msg.eml --email you@domain --password 'pw'\n"
        "  mailtm.py messages save-atts <MSG_ID> --dir ./downloads --email you@domain --password 'pw'\n"
    )
    p = argparse.ArgumentParser(description=app_desc, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_login = sub.add_parser("login", help="Authenticate and print /me")
    sp_login.add_argument("--email", required=True)
    sp_login.add_argument("--password", required=True)

    sp_acc = sub.add_parser("account", help="Account operations")
    acc_sub = sp_acc.add_subparsers(dest="acc_cmd", required=True)

    sp_acc_create = acc_sub.add_parser("create", help="Create account")
    sp_acc_create.add_argument("--password", required=True)
    sp_acc_create.add_argument("--local")
    sp_acc_create.add_argument("--domain")
    sp_acc_create.add_argument("--random", action="store_true")
    sp_acc_create.add_argument("--print-login", action="store_true")

    sp_acc_me = acc_sub.add_parser("me", help="Show /me")
    sp_acc_me.add_argument("--email", required=True)
    sp_acc_me.add_argument("--password", required=True)

    sp_acc_get = acc_sub.add_parser("get", help="Get account by id")
    sp_acc_get.add_argument("id")
    sp_acc_get.add_argument("--email", required=True)
    sp_acc_get.add_argument("--password", required=True)

    sp_acc_delete = acc_sub.add_parser("delete", help="Delete account")
    sp_acc_delete.add_argument("--email", required=True)
    sp_acc_delete.add_argument("--password", required=True)

    sp_acc_delete_id = acc_sub.add_parser("delete-id", help="Delete account by id")
    sp_acc_delete_id.add_argument("id")
    sp_acc_delete_id.add_argument("--email", required=True)
    sp_acc_delete_id.add_argument("--password", required=True)

    sp_dom = sub.add_parser("domains", help="List available domains")
    sp_dom.add_argument("--page", type=int, default=1)

    sp_dom_get = sub.add_parser("domain", help="Get domain by id")
    sp_dom_get.add_argument("id")

    sp_msg = sub.add_parser("messages", help="Message operations")
    msg_sub = sp_msg.add_subparsers(dest="msg_cmd", required=True)

    sp_msg_list = msg_sub.add_parser("list", help="List messages")
    sp_msg_list.add_argument("--email", required=True)
    sp_msg_list.add_argument("--password", required=True)
    sp_msg_list.add_argument("--page", type=int, default=1)

    sp_msg_read = msg_sub.add_parser("read", help="Read message")
    sp_msg_read.add_argument("id")
    sp_msg_read.add_argument("--email", required=True)
    sp_msg_read.add_argument("--password", required=True)
    sp_msg_read.add_argument("--mark-seen", action="store_true")

    sp_msg_latest = msg_sub.add_parser("latest", help="Read newest message")
    sp_msg_latest.add_argument("--email", required=True)
    sp_msg_latest.add_argument("--password", required=True)
    sp_msg_latest.add_argument("--mark-seen", action="store_true")

    sp_msg_delete = msg_sub.add_parser("delete", help="Delete message")
    sp_msg_delete.add_argument("id")
    sp_msg_delete.add_argument("--email", required=True)
    sp_msg_delete.add_argument("--password", required=True)

    sp_msg_seen = msg_sub.add_parser("mark-seen", help="Mark seen")
    sp_msg_seen.add_argument("id")
    sp_msg_seen.add_argument("--email", required=True)
    sp_msg_seen.add_argument("--password", required=True)

    sp_msg_src = msg_sub.add_parser("save-source", help="Save raw .eml")
    sp_msg_src.add_argument("id")
    sp_msg_src.add_argument("--out", required=True)
    sp_msg_src.add_argument("--email", required=True)
    sp_msg_src.add_argument("--password", required=True)

    sp_msg_atts = msg_sub.add_parser("save-atts", help="Download attachments")
    sp_msg_atts.add_argument("id")
    sp_msg_atts.add_argument("--dir", required=True)
    sp_msg_atts.add_argument("--email", required=True)
    sp_msg_atts.add_argument("--password", required=True)

    return p


# --------------------------
# Main
# --------------------------

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    client = MailTMClient()

    if args.cmd == "login":
        client.login(args.email, args.password)
        print_account_info(client.me())
        return

    if args.cmd == "account":
        if args.acc_cmd == "create":
            domain = args.domain or client.pick_domain()
            local = args.local or (_rand_local_part() if args.random else None)
            if not local:
                print("Need --local or --random")
                sys.exit(2)
            address = f"{local}@{domain}"
            acct = client.create_account(address, args.password)
            print("Account created")
            print(json.dumps(acct, indent=2, ensure_ascii=False))
            if args.print_login:
                client.login(address, args.password)
                print_account_info(client.me())
            return
        if args.acc_cmd == "me":
            client.login(args.email, args.password)
            print_account_info(client.me())
            return
        if args.acc_cmd == "get":
            client.login(args.email, args.password)
            data = client.get_account(args.id)
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return
        if args.acc_cmd == "delete":
            client.login(args.email, args.password)
            acc_id = client.me().get("id")
            if not acc_id:
                print("Cannot determine account id from /me")
                sys.exit(3)
            client.delete_account(acc_id)
            print("Account deleted.")
            return
        if args.acc_cmd == "delete-id":
            client.login(args.email, args.password)
            client.delete_account(args.id)
            print("Account deleted.")
            return

    if args.cmd == "domains":
        print_domains(client.list_domains(page=args.page))
        return

    if args.cmd == "domain":
        data = client.get_domain(args.id)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if args.cmd == "messages":
        client.login(args.email, args.password)
        if args.msg_cmd == "list":
            print_list(client.list_messages(page=args.page))
            return
        if args.msg_cmd == "read":
            msg = client.get_message(args.id)
            if args.mark_seen and not msg.get("seen"):
                client.mark_seen(args.id)
                msg = client.get_message(args.id)
            print_message(msg)
            return
        if args.msg_cmd == "latest":
            items = _sort_desc_by_created(client.list_messages(page=1).get("hydra:member", []))
            if not items:
                print("(inbox empty)")
                return
            latest = items[0]
            mid = latest.get("id")
            msg = client.get_message(mid)
            if args.mark_seen and not msg.get("seen"):
                client.mark_seen(mid)
                msg = client.get_message(mid)
            print_message(msg)
            return
        if args.msg_cmd == "delete":
            client.delete_message(args.id)
            print("Message deleted.")
            return
        if args.msg_cmd == "mark-seen":
            client.mark_seen(args.id)
            print("Message marked seen.")
            return
        if args.msg_cmd == "save-source":
            data = client.get_message_source(args.id)
            with open(args.out, "wb") as f:
                f.write(data)
            print(f"Saved EML to {args.out}")
            return
        if args.msg_cmd == "save-atts":
            msg = client.get_message(args.id)
            atts = client.list_attachments(msg)
            if not atts:
                print("No attachments.")
                return
            os.makedirs(args.dir, exist_ok=True)
            count = 0
            for a in atts:
                att_id = a.get("id")
                fname = a.get("filename") or f"att_{att_id or count}"
                blob = client.download_attachment(args.id, att_id)
                path = os.path.join(args.dir, fname)
                with open(path, "wb") as f:
                    f.write(blob)
                print(f"Saved {fname} ({a.get('contentType')}, {a.get('size')} bytes)")
                count += 1
            print(f"Saved {count} attachment(s) to {args.dir}")
            return


if __name__ == "__main__":
    main()
