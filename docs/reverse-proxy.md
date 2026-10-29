# Reverse proxy

The proxy carries the traffic, not DryDock: a DryDock restart cuts nothing. Your Compose files get neutral labels:

```yaml
    labels:
      - expose.host=music.example.org   # several hosts: comma-separated
      - expose.port=3000                # the container port
      - expose.private=false            # default: private
```

The proxy stack runs DryDock's **proxy sync** next to the proxy. It reads these labels from the running containers and writes the proxy's config:

- **Traefik:** a file for Traefik's file provider, which Traefik watches.
- **SWAG** (nginx): one server block per service, checked with `nginx -t`, then reloaded.
- **Caddy:** the whole Caddyfile, loaded with `caddy reload`. Hosts are grouped under wildcard sites, so Caddy asks for one certificate per domain.

A config the proxy refuses is put back to the previous one, so a bad label never takes the proxy down. The labels are real Docker labels, so a plain `docker compose up` keeps them. To switch proxy, stop the old proxy stack and create the new one: your stacks stay as they are.

1. Point `*.<domain>` at your public IP (for example a CNAME to your dynamic DNS name), and forward ports 80 and 443 of the internet router to the Docker host.
2. On the **Proxy** page, set the domain. Then pick a proxy (Traefik, SWAG or Caddy) and how it gets its certificates:
   - **A DNS provider** (OVH, Cloudflare, or another one Traefik or SWAG knows by name): one wildcard certificate per domain, so your service names never appear in public certificate logs. It needs an API token that can edit the zone's DNS records (Let's Encrypt checks a TXT record). A dynamic DNS login is not enough.
   - **The HTTP challenge**: no DNS API, any domain. One certificate per name, through port 80; the names appear in public certificate logs. Traefik and Caddy only: SWAG would need every name up front.
3. Fill in the stack's `.env` tab (`LAN_RANGES`, `TRUSTED_IPS`, the token), stop any other proxy on ports 80 and 443, and run **up**.
   - SWAG reads the DNS token from a file: after the first up, fill in `PROXY_DATA/swag/dns-conf/<provider>.ini` and restart `swag`.
   - Caddy's official image has no DNS modules: with a DNS provider, the first up builds one. It takes a few minutes on a Pi. Caddy knows OVH and Cloudflare here.
   - Traefik with another provider passes the whole `.env` to Traefik: add the variables listed for it at <https://go-acme.github.io/lego/dns/>.
4. On a stack page, open **Services**, pick a service, a name and its container port, then save and run **up**.

- **Private** services only answer an IP allowlist: `LAN_RANGES`, your current public IP and `TRUSTED_IPS`. The public IP is in it because LAN and VPN clients often come back through it (hairpin NAT). The sync refreshes it every 5 minutes. **Public** services answer everyone.
- Every service sends HSTS (`Strict-Transport-Security`): browsers stick to HTTPS for its name.
- One wildcard certificate covers every service, so your service names never appear in public certificate logs.
- Exposed services join the shared `proxy` network and keep their `default` one. The proxy reaches them by container name, so a recreate breaks nothing. **Remove** in the panel takes the labels and the network out again.
- A service with `network_mode: host` (Home Assistant) is reached through `host.docker.internal`, which the templates map to the host.
- fail2ban on the host reads the proxy's access log (`PROXY_DATA/logs/access.log`) and never bans the allowlist (`PROXY_DATA/allowlist.txt`). Set its jails on the **Proxy** page, **Security** tab. The rules match a log format, not a proxy: text for Traefik and SWAG, JSON for Caddy. The "unknown host names" template bans clients that ask for names no route claims (`tototo.example.org`), which a wildcard DNS record answers for: Traefik and Caddy only, since nginx's log does not say whether a 404 came from a route.
- The panel rewrites the file in the editor, comments included, and shows the diff. Nothing is saved until you save. Older `traefik.*` or `swag*` labels on a service are replaced.

The labels are listed in the README: [Labels](../README.md#labels).
