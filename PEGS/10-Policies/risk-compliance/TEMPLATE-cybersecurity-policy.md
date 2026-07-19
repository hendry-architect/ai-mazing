---
id: pegs-l12-cybersecurity-policy
type: template
library: L12-enterprise-risk-compliance
title: Cybersecurity Governance Policy
version: 0.1.0
status: template
owner: founder
---

# Cybersecurity Governance Policy — <Enterprise>

> Baseline for a clinical-grade enterprise: HIPAA Security Rule aligned,
> sized for the team we actually have.

## 1. Identity & access

- MFA on everything that supports it — no exceptions for seniority.
- Access per role tier (Authority Matrix); least privilege; quarterly
  access review ⚙; same-day revocation on exit (offboarding SOP).
- Password manager mandatory; no shared credentials (break-glass accounts
  sealed and logged).

## 2. Devices & data

- Enterprise data on managed/known devices only; full-disk encryption on;
  auto-lock ≤5 min.
- PHI lives in the EHR and BAA-covered systems ONLY — never in email
  bodies, texts, personal drives, or AI tools without BAA (AI Usage Policy).
- Backups: automatic, tested restores quarterly ⚙ (a backup never restored
  is a hope).

## 3. Human layer (the real perimeter)

- Security awareness training annually + phishing drills ⚙; reporting a
  suspected click is praised, hiding one is the offense.
- Wire/payment verification: callback rule (Treasury Policy §2) — finance
  never acts on email instructions alone.

## 4. Vendors

BAA before any PHI touches a vendor · security posture question in every
procurement · vendor list with data-access level maintained with the
dependency inventory (BCP §3).

## 5. Monitoring & response

Logs on for critical systems · suspected incident → Incident Response SOP
immediately (cyber carrier before remediation, SEV-1) · annual risk
analysis (also HIPAA C-03) drives next year's hardening priorities.

## 6. Governance

Owner: <role> · reviewed annually · exceptions are written, time-boxed,
Founder-approved — a permanent exception is a policy change wearing a
disguise.
