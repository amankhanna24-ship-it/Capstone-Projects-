"""
make_sample_corpus.py — creates a small but realistic company corpus in data/raw/.

    python scripts/make_sample_corpus.py

What you get (all fictional, company = "Northwind Talent Ltd"):
    policies/   HR-POL-012 remote working (PDF), FIN-POL-004 expenses v1 + v2 (PDF)
    contracts/  CTR-2025-044 Acme Cloud MSA (DOCX), CTR-2026-009 Nimbus Payroll DPA (DOCX)
    runbooks/   RB-NET-007 VPN outage (Markdown), RB-DB-003 Postgres failover (Markdown)
    web/        IT security FAQ (HTML page)
    tickets/    IT incident tickets (CSV, one ticket = one chunk)

The corpus is designed to expose each retrieval weakness:
  * exact IDs (INC-4821, RB-DB-003) .......... semantic search struggles, BM25 wins
  * paraphrase ("work from abroad") .......... BM25 struggles, embeddings win
  * two versions of the expense policy ....... needs date / latest-version filters
  * mixed departments ........................ needs department (tenant) filters

Replace these files with your own documents and edit data/manifest.json to match.
"""

from __future__ import annotations

import csv
from pathlib import Path

from docx import Document
from fpdf import FPDF

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------
def write_pdf(path: Path, title: str, meta_line: str, sections: list[tuple[str, str]]) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, meta_line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for heading, body in sections:
        if heading == "<pagebreak>":
            pdf.add_page()
            continue
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for para in body.strip().split("\n\n"):
            pdf.multi_cell(0, 5, " ".join(para.split()), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        pdf.ln(2)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


REMOTE_POLICY = [
    ("1. Purpose and scope", """
This policy explains how employees of Northwind Talent Ltd may work remotely or on a hybrid
pattern. It applies to all permanent and fixed-term employees in the UK, the Netherlands and
India. Contractors are covered by their own agreements and are out of scope.

The policy owner is the Head of People Operations. Questions should be raised with your HR
Business Partner or through the People Helpdesk."""),
    ("2. Hybrid working pattern", """
The default pattern is hybrid: a minimum of two days per week in the office (anchor days are
Tuesday and Thursday) and up to three days working from home. Teams may agree a different
anchor day with their Director, provided at least 40% of working time is spent in the office
averaged over a calendar month.

Fully remote contracts are by exception only and require approval from the relevant Director
and the Head of People Operations."""),
    ("3. Working from another country", """
Employees may work temporarily from a country other than their country of employment for up
to 20 working days in any rolling 12-month period. This is known as Temporary Overseas Working.

Requests must be submitted through the HR portal at least 15 working days before travel using
form HR-F-031. Approval is required from your line manager, the Tax team and Information
Security. Some countries are excluded because of tax, immigration or data-protection risk;
the current list is maintained on the People intranet.

Working from abroad for longer than 20 days, or on a recurring basis, is treated as an
international assignment and is handled by the Global Mobility team."""),
    ("<pagebreak>", ""),
    ("4. Home office equipment and allowance", """
New joiners receive a laptop, monitor, keyboard and headset. In addition, employees on a
hybrid or remote pattern may claim a one-off home office allowance of GBP 300 (UK),
EUR 350 (Netherlands) or INR 20,000 (India) for a desk, chair or lighting. Receipts must be
submitted within 60 days through the expenses system under category HOME-EQUIP.

A monthly connectivity allowance of GBP 25 / EUR 25 / INR 1,500 is paid through payroll to
employees who work from home at least two days per week."""),
    ("5. Health, safety and security", """
Employees must complete the Display Screen Equipment (DSE) self-assessment within the first
month of hybrid working and repeat it every two years. Company devices must only be used on
secured networks; public Wi-Fi must always be used with the company VPN switched on.

Confidential documents must not be printed at home. Any loss of a device must be reported to
the IT Service Desk within one hour."""),
    ("6. Review", """
This policy is reviewed annually by People Operations. Version 3.0 replaces version 2.1 and
takes effect on 15 January 2026."""),
]

EXPENSE_V1 = [
    ("1. Scope", """
This policy sets out the rules for business travel and expenses at Northwind Talent Ltd. It
applies to all employees and to contractors who are permitted to claim expenses under their
contract."""),
    ("2. Approval limits", """
All expense claims must be approved by the employee's line manager. Any single claim above
GBP 500 also requires approval from the budget-holding Director. Claims above GBP 2,500 require
CFO approval.

Claims must be submitted within 30 days of the expense being incurred."""),
    ("3. Hotels", """
The maximum nightly hotel rate, including taxes, is GBP 150 in London, GBP 110 elsewhere in
the UK, EUR 140 in Amsterdam and INR 7,000 in Bangalore, Chennai or Mumbai. Rates above the cap
require prior Director approval."""),
    ("4. Meals and subsistence", """
Employees travelling overnight may claim up to GBP 35 per day for meals. Alcohol is not
reimbursable except at approved client entertainment events."""),
    ("5. Rail and air travel", """
Rail travel should be standard class. First class is allowed for journeys over three hours.
Flights under six hours must be economy class."""),
    ("6. Effective date", """
Version 1.0. Effective from 1 April 2024."""),
]

EXPENSE_V2 = [
    ("1. Scope", """
This policy sets out the rules for business travel and expenses at Northwind Talent Ltd. It
applies to all employees and to contractors who are permitted to claim expenses under their
contract. Version 2.0 replaces version 1.0 in full."""),
    ("2. Approval limits", """
All expense claims must be approved by the employee's line manager. Any single claim above
GBP 750 also requires approval from the budget-holding Director. Claims above GBP 3,000 require
CFO approval.

Claims must be submitted within 45 days of the expense being incurred. Late claims are
rejected automatically unless the Finance Controller grants an exception."""),
    ("3. Hotels", """
The maximum nightly hotel rate, including taxes, is GBP 180 in London, GBP 120 elsewhere in
the UK, EUR 160 in Amsterdam and INR 8,500 in Bangalore, Chennai or Mumbai. Bookings must be
made through the corporate travel portal; bookings made elsewhere are only reimbursed up to
the cap."""),
    ("4. Meals and subsistence", """
Employees travelling overnight may claim up to GBP 40 per day for meals (EUR 45 in the
Netherlands, INR 2,500 in India). Alcohol is not reimbursable except at approved client
entertainment events."""),
    ("5. Rail and air travel", """
Rail travel must be standard class for all journeys. Flights under six hours must be economy
class; premium economy is allowed for flights over six hours."""),
    ("6. Effective date", """
Version 2.0. Effective from 1 April 2026. Changes from version 1.0: higher hotel caps, higher
meal allowance, Director approval threshold raised from GBP 500 to GBP 750, claim window
extended to 45 days, and first-class rail removed."""),
]


# ---------------------------------------------------------------------------
# DOCX contracts (clause-structured)
# ---------------------------------------------------------------------------
def write_docx(path: Path, title: str, intro: str, clauses: list[tuple[str, str]]) -> None:
    doc = Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph(intro)
    for heading, body in clauses:
        doc.add_heading(heading, level=1)
        for para in body.strip().split("\n\n"):
            doc.add_paragraph(" ".join(para.split()))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


ACME_MSA = [
    ("1. Definitions", """
"Services" means the managed cloud hosting, backup and monitoring services described in
Schedule 1. "Monthly Uptime" means the percentage of minutes in a calendar month during which
the production environment is available, excluding Planned Maintenance."""),
    ("2. Term and renewal", """
This Agreement starts on 1 July 2025 and continues for an initial term of 36 months. It then
renews automatically for successive 12-month periods unless either party gives written notice
of non-renewal at least 90 days before the end of the current term."""),
    ("3. Service levels", """
Acme Cloud shall provide Monthly Uptime of at least 99.9% for the production environment.
Planned Maintenance must be notified 5 business days in advance and may not exceed 4 hours
per month.

If Monthly Uptime falls below 99.9%, Northwind is entitled to service credits of 5% of the
monthly fee for each 0.1% (or part) below the target, capped at 30% of the monthly fee.
Service credits must be claimed within 30 days of the end of the affected month."""),
    ("4. Data residency and security", """
All Northwind production data shall be stored and processed only in data centres located in
the European Union (Frankfurt, Amsterdam) and India (Mumbai). Acme Cloud shall maintain ISO
27001 certification and notify Northwind of any personal data breach within 24 hours of
becoming aware of it."""),
    ("5. Fees and payment", """
Fees are set out in Schedule 2 and are invoiced monthly in arrears. Invoices are payable within
45 days. Fees may be increased once per year by no more than the UK CPI rate plus 2%."""),
    ("6. Termination", """
Either party may terminate this Agreement for convenience by giving at least 90 days' written
notice, but not before the first 12 months of the initial term have elapsed. Either party may
terminate immediately on written notice if the other party commits a material breach that is
not remedied within 30 days.

Northwind may also terminate if Monthly Uptime falls below 99.0% in any three months within a
rolling six-month period."""),
    ("7. Limitation of liability", """
Each party's total liability under this Agreement is capped at the total fees paid in the 12
months before the claim. The cap does not apply to breach of confidentiality, data-protection
obligations or death and personal injury caused by negligence."""),
    ("8. Exit assistance", """
On termination, Acme Cloud shall provide up to 60 days of exit assistance, including a full
export of Northwind data in an industry-standard format, at the then-current professional
services rates."""),
]

NIMBUS_DPA = [
    ("1. Subject matter", """
Nimbus Payroll Services Pvt Ltd processes employee payroll data on behalf of Northwind Talent
Ltd for employees in India and the Netherlands. Northwind is the controller and Nimbus is the
processor."""),
    ("2. Categories of data", """
Names, employee IDs, bank details, tax identifiers, salary, deductions and statutory benefit
information. No special-category data is processed except where required by statutory leave
calculations."""),
    ("3. Location of processing", """
Payroll data is processed in Nimbus data centres in Chennai and Pune, India, with an encrypted
backup in Frankfurt, Germany. Transfers of Netherlands employee data to India are covered by
the EU Standard Contractual Clauses (Module 2) attached as Annex 3."""),
    ("4. Sub-processors", """
Nimbus may only appoint sub-processors listed in Annex 2. Northwind must be given 30 days'
notice of any new sub-processor and may object on reasonable data-protection grounds."""),
    ("5. Security and breach notification", """
Nimbus shall encrypt data at rest (AES-256) and in transit (TLS 1.2 or higher), enforce
multi-factor authentication for all administrative access and notify Northwind of a personal
data breach without undue delay and in any case within 24 hours."""),
    ("6. Retention and deletion", """
Payroll records are retained for 8 years after the end of the tax year to which they relate,
and then securely deleted. On termination Nimbus shall return all data within 30 days and
delete remaining copies within 60 days, providing a deletion certificate."""),
]


# ---------------------------------------------------------------------------
# Markdown runbooks
# ---------------------------------------------------------------------------
RB_NET_007 = """# RB-NET-007 — Remote-access VPN outage

**Owner:** Network Operations · **Severity:** P1 when more than 50 users are affected · **Last reviewed:** 10 Nov 2025

## Symptoms
- Users see *"Error 809: The network connection between your computer and the VPN server could not be established"*.
- GlobalConnect client stuck on "Authenticating…" for more than 60 seconds.
- Spike in Service Desk tickets tagged `vpn`.

## Triage
1. Check the VPN dashboard in Grafana (`net-vpn-overview`) for gateway CPU and active sessions.
2. Confirm whether the issue affects one region (London, Amsterdam, Bangalore) or all.
3. Check the certificate on gateway `vpn-gw-01`/`vpn-gw-02`: `openssl s_client -connect vpn.northwind.example:443`.
4. If more than 50 users are affected, raise a P1 incident and page the Network on-call.

## Common causes and fixes
### Expired gateway certificate
The most frequent root cause (see INC-4821). Renew the certificate from the internal CA, upload to both gateways and restart the `ike` service. Total time is usually 20 minutes.

### RADIUS / MFA timeout
If authentication hangs, check the RADIUS proxy `rad-01`. Restart the `freeradius` service and confirm the MFA provider status page. Increase the client timeout to 90 seconds as a temporary workaround.

### Error 809 on home routers
Error 809 for a single user is usually a home router blocking UDP 500/4500. Ask the user to switch the client to SSL/TCP 443 mode in *Settings → Protocol*.

## Escalation
Escalate to the Network Lead after 30 minutes without progress on a P1. Communicate status to users every 30 minutes through the IT status page.

## Post-incident
Raise a problem record, attach the timeline, and update this runbook if a new cause was found.
"""

RB_DB_003 = """# RB-DB-003 — PostgreSQL primary failover

**Owner:** Platform Engineering · **Applies to:** `pg-core` cluster (Patroni, 3 nodes) · **Last reviewed:** 20 Feb 2026

## When to use
Use this runbook when the primary database `pg-core-1` is unavailable for more than 2 minutes and Patroni has **not** failed over automatically, or when a planned switchover is required for maintenance.

## Pre-checks
1. Confirm the primary is really down: `patronictl -c /etc/patroni.yml list`.
2. Check replication lag on the replicas; do **not** promote a replica that is more than 30 seconds behind unless the Incident Manager approves data loss.
3. Freeze deployments in the release pipeline.

## Promote a replica to primary
1. Run `patronictl -c /etc/patroni.yml failover --candidate pg-core-2`.
2. Confirm the new leader with `patronictl list` — `pg-core-2` must show role `Leader`.
3. The PgBouncer pool picks up the new primary through the Consul service `pg-core-primary`; verify with `psql -h pg-core-primary.service -c "select pg_is_in_recovery();"` which must return `f`.
4. Run the smoke test job `db-smoke` in the CI pipeline.

## Rebuild the old primary
Once the old node is healthy, re-initialise it as a replica: `patronictl reinit pg-core pg-core-1`. Monitor replication until lag is under 1 second.

## Rollback
If the new primary misbehaves within 15 minutes, switch back with `patronictl switchover --candidate pg-core-1` provided its data is intact.

## Communication
Post in `#inc-bridge` at each step. The RPO target for `pg-core` is 30 seconds and the RTO target is 15 minutes.
"""


# ---------------------------------------------------------------------------
# HTML web page
# ---------------------------------------------------------------------------
SECURITY_FAQ_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>IT Security FAQ — Northwind Intranet</title></head>
<body>
<nav>Home · IT · Security</nav>
<main>
<h1>IT Security FAQ</h1>
<p>Last updated 1 September 2025 by the Information Security team.</p>

<h2>Passwords and multi-factor authentication</h2>
<p>Passwords must be at least 14 characters. You do not need to change your password on a schedule,
only when you suspect it has been exposed. Multi-factor authentication (MFA) is mandatory for email,
VPN, the HR portal and all finance systems.</p>
<h3>Can I use email on my personal phone?</h3>
<p>Yes, through the Outlook app only, enrolled in the company's mobile device management (Intune).
MFA is mandatory on personal phones and the app enforces a 6-digit PIN. Native mail apps are blocked.</p>

<h2>Phishing</h2>
<p>If you clicked a link or opened an attachment in a suspicious email, disconnect from the network,
do not enter any more credentials and call the IT Service Desk on extension 4444 immediately. Then
use the <em>Report Phish</em> button in Outlook. Reporting quickly matters more than embarrassment:
there is no penalty for reporting a genuine mistake.</p>

<h2>Lost or stolen devices</h2>
<p>Report a lost laptop or phone to the IT Service Desk within one hour. The device will be remotely
locked and wiped. A police reference number is required for stolen devices.</p>

<h2>USB drives and file sharing</h2>
<p>USB storage devices are blocked on company laptops. Share files internally through SharePoint and
externally only through the approved secure file transfer service. Personal cloud storage
(e.g. personal Dropbox or Google Drive) must not be used for company data.</p>

<h2>Travelling abroad with a laptop</h2>
<p>Inform Information Security before taking a company laptop to a country outside the UK, EU or India.
A loaner laptop may be issued for high-risk destinations.</p>
</main>
<footer>© Northwind Talent Ltd — internal use only</footer>
</body></html>
"""


# ---------------------------------------------------------------------------
# CSV tickets
# ---------------------------------------------------------------------------
TICKETS = [
    # ticket_id, opened, priority, category, summary, resolution, related
    ("INC-4821", "2025-11-03", "P1", "vpn",
     "Company-wide VPN outage, users in London and Amsterdam getting Error 809 from 08:40.",
     "Root cause: TLS certificate on vpn-gw-01 and vpn-gw-02 expired overnight. Certificate renewed from internal CA "
     "and ike service restarted at 09:25. Problem record PRB-0192 raised to automate certificate expiry alerts.",
     "RB-NET-007"),
    ("INC-4830", "2025-11-05", "P3", "vpn",
     "Single user in Bangalore cannot connect to VPN from home, Error 809.",
     "Home router blocking UDP 4500. User switched GlobalConnect to SSL/TCP 443 mode. Resolved.",
     "RB-NET-007"),
    ("INC-4902", "2025-12-12", "P2", "vpn",
     "VPN authentication hanging for about 40 users, stuck on Authenticating.",
     "RADIUS proxy rad-01 memory exhaustion. freeradius restarted; memory limit raised. Client timeout set to 90s.",
     "RB-NET-007"),
    ("INC-5017", "2026-01-21", "P1", "database",
     "pg-core-1 primary unreachable after storage controller failure; Patroni did not fail over.",
     "Manual failover to pg-core-2 per RB-DB-003 at 14:07. Replication lag at promotion was 4 seconds. "
     "pg-core-1 reinitialised as replica next day. Total outage 11 minutes, within RTO.",
     "RB-DB-003"),
    ("INC-5033", "2026-02-02", "P3", "laptop",
     "New joiner laptop not receiving Intune policies; Outlook app blocked on personal phone.",
     "Device was not enrolled in Intune. Re-enrolled; MFA registration completed. Resolved.",
     ""),
    ("INC-5101", "2026-03-15", "P2", "security",
     "Employee clicked a phishing link imitating the HR portal and entered credentials.",
     "Account password reset, sessions revoked, MFA re-registered. Phishing domain blocked at the mail gateway. "
     "No evidence of data access.",
     ""),
    ("INC-5188", "2026-05-08", "P3", "expenses",
     "Expense claim for London hotel at GBP 175 rejected by system as above cap.",
     "Claim dated before 1 April 2026 so the old GBP 150 cap applied (FIN-POL-004 v1). Director approval obtained "
     "and claim resubmitted.",
     "FIN-POL-004"),
    ("INC-5240", "2026-06-19", "P2", "database",
     "Planned switchover of pg-core for kernel patching.",
     "Switchover to pg-core-3 completed in 3 minutes using patronictl switchover. db-smoke passed.",
     "RB-DB-003"),
]


def main() -> None:
    write_pdf(RAW / "policies" / "HR-POL-012_remote_hybrid_working.pdf",
              "HR-POL-012 Remote and Hybrid Working Policy",
              "Northwind Talent Ltd | People Operations | Version 3.0 | Effective 15 January 2026",
              REMOTE_POLICY)
    write_pdf(RAW / "policies" / "FIN-POL-004_travel_expenses_v1.pdf",
              "FIN-POL-004 Travel and Expenses Policy (v1.0)",
              "Northwind Talent Ltd | Finance | Version 1.0 | Effective 1 April 2024",
              EXPENSE_V1)
    write_pdf(RAW / "policies" / "FIN-POL-004_travel_expenses_v2.pdf",
              "FIN-POL-004 Travel and Expenses Policy (v2.0)",
              "Northwind Talent Ltd | Finance | Version 2.0 | Effective 1 April 2026",
              EXPENSE_V2)

    write_docx(RAW / "contracts" / "CTR-2025-044_acme_cloud_msa.docx",
               "CTR-2025-044 Master Services Agreement — Acme Cloud Ltd",
               "This Master Services Agreement is made between Northwind Talent Ltd (\"Northwind\") and "
               "Acme Cloud Ltd (\"Acme Cloud\"), effective 1 July 2025.",
               ACME_MSA)
    write_docx(RAW / "contracts" / "CTR-2026-009_nimbus_payroll_dpa.docx",
               "CTR-2026-009 Data Processing Agreement — Nimbus Payroll Services",
               "This Data Processing Agreement is made between Northwind Talent Ltd and Nimbus Payroll Services "
               "Pvt Ltd, effective 1 March 2026.",
               NIMBUS_DPA)

    (RAW / "runbooks").mkdir(parents=True, exist_ok=True)
    (RAW / "runbooks" / "RB-NET-007_vpn_outage.md").write_text(RB_NET_007, encoding="utf-8")
    (RAW / "runbooks" / "RB-DB-003_postgres_failover.md").write_text(RB_DB_003, encoding="utf-8")

    (RAW / "web").mkdir(parents=True, exist_ok=True)
    (RAW / "web" / "it_security_faq.html").write_text(SECURITY_FAQ_HTML, encoding="utf-8")

    (RAW / "tickets").mkdir(parents=True, exist_ok=True)
    with open(RAW / "tickets" / "it_incidents.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "opened", "priority", "category", "summary", "resolution", "related_doc"])
        w.writerows(TICKETS)

    for p in sorted(RAW.rglob("*")):
        if p.is_file():
            print(f"  wrote {p.relative_to(RAW.parent.parent)}  ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
