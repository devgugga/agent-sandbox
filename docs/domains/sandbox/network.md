# Network & Firewall Architecture

## Firewall Ruleset (nftables)

The firewall ruleset is initialized by a short-lived init container possessing `CAP_NET_ADMIN`. Once applied, the agent container (running strictly as uid 1000 without `CAP_NET_ADMIN`) cannot modify or flush the table.

The nftables table `inet asb` defines chain `out` with policy `drop` and exactly four sequential rules:

```nft
table inet asb {
  chain out {
    type filter hook output priority filter; policy drop;

    # 1. Allow returning packets for established/related connections
    ct state established,related accept

    # 2. Allow inter-container communication on loopback
    oif "lo" accept

    # 3. Allow egress exclusively for proxy daemon uid
    meta skuid 900 accept
  }
}
```

## Egress Proxy (Squid)

Outbound external HTTP/HTTPS connectivity is mediated exclusively through Squid running on port 3128:

- **CONNECT Tunneling**: Squid enforces destination filtering on TLS connections (`CONNECT` method) without terminating TLS (no MITM CA certificates required).
- **Domain Allowlist**: Allowlist filtering is performed on domain names (`dstdomain`), resolved upstream by Squid. The agent container does not receive DNS access, preventing DNS tunneling and exfiltration.
- **Subdomain Rules**: A domain prefixed with `.` (e.g. `.github.com`) matches both the apex domain (`github.com`) and all subdomains (`api.github.com`, `raw.githubusercontent.com`).
