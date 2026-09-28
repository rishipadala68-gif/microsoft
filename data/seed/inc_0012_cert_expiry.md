# Post-Mortem: INC-0012 TLS certificate expired on payments-gateway

## Summary
On 2024-05-18, payments-gateway failed to establish TLS handshakes with external banking partners.

## Symptoms
- TLS handshake errors: x509: certificate has expired
- Inability to process credit card checkouts
- Service: payments-gateway

## Root Cause
Cert renewal cron silently failing after a service-account rotation in `infra/crons/renew_certs.sh`.

## Resolution Steps
1. Executed manual certificate renewal with Let's Encrypt.
2. Updated service account credentials in cron job.
3. Followed runbook RB-cert-expiry.
