# RB-NET-007 — Remote-access VPN outage

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
