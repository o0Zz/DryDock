# Reverse proxy

The proxy carries the traffic, not DryDock: a DryDock restart cuts nothing. Your Compose files get neutral labels:

```yaml
    labels:
      - expose.host=music.example.org   # several hosts: comma-separated
      - expose.port=3000                # the container port
      - expose.private=false            # default: private
```

The proxy stack runs DryDock's **proxy sync** next to Traefik. It reads these labels from the running containers and writes a file for Traefik's file provider, which Traefik watches. Traefik keeps its last good config when it refuses a file, so a bad label never takes it down. The labels are real Docker labels, so a plain `docker compose up` keeps them.

1. Point `*.<domain>` at your public IP, and forward ports 80 and 443 of the internet router to the Docker host.
   - DryDock does not update DNS records. If your public IP changes, let your router's dynamic DNS do it, or run a small updater such as `qmcgaw/ddns-updater` (OVH, Cloudflare and many others) as its own stack, and point `*.<domain>` at that name with a CNAME.
2. On the **Proxy** page, set the domain. Then create the Traefik stack and pick how it gets its certificates:
   - **A DNS provider** (OVH, Cloudflare, or any other one lego knows by name): one wildcard certificate per domain, so your service names never appear in public certificate logs. It needs an API token that can edit the zone's DNS records (Let's Encrypt checks a TXT record). A dynamic DNS login is not enough.
   - **The HTTP challenge**: no DNS API, any domain. One certificate per name, through port 80; the names appear in public certificate logs.
3. Fill in the stack's `.env` tab (`LAN_RANGES`, `TRUSTED_IPS`, the token), stop any other proxy on ports 80 and 443, and run **up**.
   - With another provider the whole `.env` is passed to Traefik: add the variables listed for it at <https://go-acme.github.io/lego/dns/>.
4. On a stack page, open **Services**, pick a service, a name and its container port, then save and run **up**.

- **Private** services only answer an IP allowlist: `LAN_RANGES`, your current public IP and `TRUSTED_IPS`. The public IP is in it because LAN and VPN clients often come back through it (hairpin NAT). The sync refreshes it every 5 minutes. **Public** services answer everyone.
- Every service sends HSTS (`Strict-Transport-Security`): browsers stick to HTTPS for its name.
- One wildcard certificate covers every service, so your service names never appear in public certificate logs.
- Exposed services join the shared `proxy` network and keep their `default` one. The proxy reaches them by container name, so a recreate breaks nothing. **Remove** in the panel takes the labels and the network out again.
- A service with `network_mode: host` (Home Assistant) is reached through `host.docker.internal`, which the template maps to the host.
- fail2ban on the host reads Traefik's access log (`PROXY_DATA/logs/access.log`) and never bans the allowlist (`PROXY_DATA/allowlist.txt`, found next to the log folder). Set its jails on the **Proxy** page, **Security** tab. The "unknown host names" template bans clients that ask for names no route claims (`tototo.example.org`), which a wildcard DNS record answers for. The "scanners" and "bad bots" templates include Debian's `botsearch-common.conf` and `apache-badbots.conf` lists. Bans go through nftables.
- The panel rewrites the file in the editor, comments included, and shows the diff. Nothing is saved until you save. Hand-written `traefik.*` labels on a service are replaced.

The labels are listed in the README: [Labels](../README.md#labels).
