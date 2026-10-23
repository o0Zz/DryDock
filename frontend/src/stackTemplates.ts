import { msg } from "./i18n";

export interface StackTemplate {
  id: string;
  label: string;
  description: string;
  /** Suggested stack name. */
  name: string;
  compose: string;
  /** Written as the stack's .env after creation (admins only). `{domain}` is filled in. */
  env?: string;
}

const BLANK = `services:
  app:
    image: nginx:latest
    restart: unless-stopped
    ports:
      - "8080:80"
`;

// The proxy sync (app/proxy_sync.py) turns the expose.* labels the Expose panel writes
// into the proxy's own config. {image} is DryDock's own image, filled in on creation.
function proxySync(proxy: string, output: string): string {
  return `  # Turns the expose.* labels of running containers into ${proxy}'s config.
  proxy-sync:
    image: {image}
    restart: unless-stopped
    command: ["python", "-m", "app.proxy_sync"]
    environment:
      PROXY: ${proxy}
      PROXY_CONTAINER: ${proxy}
      OUTPUT: ${output}
      ALLOWLIST_FILE: /data/allowlist.txt
      NETWORK: proxy
      LAN_RANGES: \${LAN_RANGES:-192.168.0.0/16}
      TRUSTED_IPS: \${TRUSTED_IPS:-}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - \${PROXY_DATA:-/data/proxy}:/data
    labels:
      # DryDock finds the sync by this label.
      - drydock.proxy-sync=true

networks:
  proxy:
    name: proxy
`;
}

// What every proxy template says about the labels, the allowlist and PROXY_DATA.
const COMMON_HELP = `#
# Your stacks carry neutral labels (expose.host, expose.port, expose.private), so they
# stay the same whatever proxy runs. proxy-sync, DryDock's own image, reads them from the
# running containers and writes this proxy's config.
#
# Private services only answer an IP allowlist: LAN_RANGES, your current public IP
# (LAN and VPN clients often come back through it) and TRUSTED_IPS.
#
# PROXY_DATA (a host folder) holds the certificates, the config, the allowlist and the
# access log. DryDock's fail2ban jails (Host page) read logs/access.log and
# allowlist.txt from there.
#
# One wildcard certificate per domain through the OVH DNS challenge: service names
# never appear in public certificate logs.`;

const TRAEFIK = `# Reverse proxy: Traefik, for the services you expose from DryDock (Expose, beside the
# Compose editor). Fill in the .env tab, stop any other proxy on ports 80 and 443, then up.
${COMMON_HELP}
services:
  traefik:
    image: traefik:v3
    container_name: traefik
    restart: unless-stopped
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --providers.docker.network=proxy
      - --providers.file.directory=/etc/traefik/dynamic
      - --providers.file.watch=true
      - --entrypoints.web.address=:80
      - --entrypoints.web.http.redirections.entrypoint.to=websecure
      - --entrypoints.web.http.redirections.entrypoint.scheme=https
      - --entrypoints.websecure.address=:443
      # Large uploads (file managers, photos) must not time out.
      - --entrypoints.websecure.transport.respondingtimeouts.readtimeout=0
      - --entrypoints.websecure.http.tls.certresolver=le
      - --entrypoints.websecure.http.tls.domains[0].main=\${PROXY_DOMAIN}
      - --entrypoints.websecure.http.tls.domains[0].sans=*.\${PROXY_DOMAIN}
      - --certificatesresolvers.le.acme.email=\${ACME_EMAIL}
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.dnschallenge.provider=ovh
      # Public resolvers: a local DNS that answers for the domain would fail the check.
      - --certificatesresolvers.le.acme.dnschallenge.resolvers=1.1.1.1:53,8.8.8.8:53
      # One line per request with the client IP, for fail2ban.
      - --accesslog=true
      - --accesslog.filepath=/logs/access.log
      - --api.dashboard=true
    environment:
      OVH_ENDPOINT: \${OVH_ENDPOINT:-ovh-eu}
      OVH_APPLICATION_KEY: \${OVH_APPLICATION_KEY}
      OVH_APPLICATION_SECRET: \${OVH_APPLICATION_SECRET}
      OVH_CONSUMER_KEY: \${OVH_CONSUMER_KEY}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - \${PROXY_DATA:-/data/proxy}/letsencrypt:/letsencrypt
      - \${PROXY_DATA:-/data/proxy}/dynamic:/etc/traefik/dynamic:ro
      - \${PROXY_DATA:-/data/proxy}/logs:/logs
    # Services with network_mode: host are reached through the host's gateway address.
    extra_hosts:
      - host.docker.internal:host-gateway
    networks:
      - proxy
    labels:
      - drydock.proxy=traefik
      # The dashboard has no login: private only. private@file comes from proxy-sync.
      - traefik.enable=true
      - traefik.http.routers.traefik.rule=Host(\`traefik.\${PROXY_DOMAIN}\`)
      - traefik.http.routers.traefik.entrypoints=websecure
      - traefik.http.routers.traefik.middlewares=private@file,hsts@file
      - traefik.http.routers.traefik.service=api@internal

${proxySync("traefik", "/data/dynamic")}`;

const SWAG = `# Reverse proxy: SWAG (nginx and certbot), for the services you expose from DryDock
# (Expose, beside the Compose editor). Fill in the .env tab, stop any other proxy on ports
# 80 and 443, then up. SWAG reads the OVH token from a file, not from .env: after the
# first up, fill in PROXY_DATA/swag/dns-conf/ovh.ini and restart swag.
${COMMON_HELP}
#
# proxy-sync writes one server block per service to site-confs/drydock-expose.conf,
# checks it with nginx -t and reloads nginx. A config nginx refuses is put back.
services:
  swag:
    image: lscr.io/linuxserver/swag:latest
    container_name: swag
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
    environment:
      PUID: "1000"
      PGID: "1000"
      TZ: Etc/UTC
      URL: \${PROXY_DOMAIN}
      SUBDOMAINS: wildcard
      VALIDATION: dns
      DNSPLUGIN: ovh
      EMAIL: \${ACME_EMAIL}
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - \${PROXY_DATA:-/data/proxy}/swag:/config
      # nginx's logs, where DryDock's fail2ban jails read them.
      - \${PROXY_DATA:-/data/proxy}/logs:/config/log/nginx
    # Services with network_mode: host are reached through the host's gateway address.
    extra_hosts:
      - host.docker.internal:host-gateway
    networks:
      - proxy
    labels:
      - drydock.proxy=swag

${proxySync("swag", "/data/swag/nginx/site-confs")}`;

const CADDY = `# Reverse proxy: Caddy, for the services you expose from DryDock (Expose, beside the
# Compose editor). Fill in the .env tab, stop any other proxy on ports 80 and 443, then up.
# Caddy's official image has no OVH DNS module, so the first up builds one: a few
# minutes on a Pi.
${COMMON_HELP}
#
# proxy-sync writes the whole Caddyfile (PROXY_DATA/caddy/Caddyfile) and runs caddy
# reload, which refuses a bad config and keeps the running one. Caddy logs JSON: set
# the log format to JSON in DryDock's fail2ban jails (Host page).
services:
  caddy:
    build:
      dockerfile_inline: |
        FROM caddy:2-builder AS builder
        RUN xcaddy build --with github.com/caddy-dns/ovh
        FROM caddy:2
        COPY --from=builder /usr/bin/caddy /usr/bin/caddy
    image: caddy-ovh:local
    container_name: caddy
    restart: unless-stopped
    environment:
      ACME_EMAIL: \${ACME_EMAIL}
      OVH_ENDPOINT: \${OVH_ENDPOINT:-ovh-eu}
      OVH_APPLICATION_KEY: \${OVH_APPLICATION_KEY}
      OVH_APPLICATION_SECRET: \${OVH_APPLICATION_SECRET}
      OVH_CONSUMER_KEY: \${OVH_CONSUMER_KEY}
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - \${PROXY_DATA:-/data/proxy}/caddy:/etc/caddy
      - \${PROXY_DATA:-/data/proxy}/caddy-data:/data
      - \${PROXY_DATA:-/data/proxy}/logs:/logs
    # Services with network_mode: host are reached through the host's gateway address.
    extra_hosts:
      - host.docker.internal:host-gateway
    networks:
      - proxy
    labels:
      - drydock.proxy=caddy

${proxySync("caddy", "/data/caddy")}`;

function proxyEnv(ovhToken: boolean): string {
  return `# Host folder for certificates, config, allowlist and access log.
PROXY_DATA=/data/proxy
# Domain of the wildcard certificate: services get <name>.<domain>.
PROXY_DOMAIN={domain}
# Let's Encrypt account e-mail (expiry notices).
ACME_EMAIL=
# Private services allow these networks, your current public IP and these IPs (comma-separated).
LAN_RANGES=192.168.0.0/16
TRUSTED_IPS=
${
  ovhToken
    ? `# OVH API token for the DNS challenge: https://eu.api.ovh.com/createToken/
# Rights: GET, POST, PUT and DELETE on /domain/zone/<domain>/*
OVH_ENDPOINT=ovh-eu
OVH_APPLICATION_KEY=
OVH_APPLICATION_SECRET=
OVH_CONSUMER_KEY=
`
    : ""
}`;
}

const PROXY_DESCRIPTION = msg(
  "HTTPS for the services you expose, with a wildcard certificate from the OVH DNS challenge. Private services only answer your LAN, your public IP and trusted IPs.",
);

export const STACK_TEMPLATES: StackTemplate[] = [
  {
    id: "blank",
    label: msg("Blank"),
    description: msg("One nginx service to start from."),
    name: "",
    compose: BLANK,
  },
  {
    id: "traefik",
    label: msg("Traefik reverse proxy"),
    description: PROXY_DESCRIPTION,
    name: "traefik",
    compose: TRAEFIK,
    env: proxyEnv(true),
  },
  {
    id: "swag",
    label: msg("SWAG reverse proxy (nginx)"),
    description: PROXY_DESCRIPTION,
    name: "swag",
    compose: SWAG,
    env: proxyEnv(false),
  },
  {
    id: "caddy",
    label: msg("Caddy reverse proxy"),
    description: PROXY_DESCRIPTION,
    name: "caddy",
    compose: CADDY,
    env: proxyEnv(true),
  },
];

/** The reverse proxy templates, for the Proxy page. */
export const PROXY_TEMPLATES = STACK_TEMPLATES.filter((template) => template.id !== "blank");
