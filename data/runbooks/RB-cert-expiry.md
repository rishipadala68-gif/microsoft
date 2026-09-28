---
id: RB-cert-expiry
title: TLS / SSL Certificate Expiry Remediation
services:
  - payments-gateway
  - web-frontend
  - auth-service
---

# RB-cert-expiry: TLS Certificate Expiration

## Symptoms
- Upstream clients logging `x509: certificate has expired` or `SSL_ERROR_EXPIRED_CERT_DATE`.
- Inability to establish mutual TLS (mTLS) with external gateways.
- 502/504 Bad Gateway from ingress reverse proxies.

## Diagnostic Steps
1. Inspect the certificate expiration timestamp:
   `echo | openssl s_client -servername <host> -connect <host>:443 2>/dev/null | openssl x509 -noout -dates`
2. Check cert-manager / Let's Encrypt automation logs:
   `kubectl logs -n cert-manager -l app=cert-manager --tail=100`

## Mitigation Steps
1. Trigger an immediate manual renewal via ACME / cert-manager:
   `kubectl cert-manager renew <certificate-name>`
2. If using static secrets, regenerate and apply updated Kubernetes secret:
   `kubectl create secret tls <secret-name> --cert=cert.pem --key=key.pem --dry-run=client -o yaml | kubectl apply -f -`
3. Reload ingress or API gateway pods to load the new certificate.
