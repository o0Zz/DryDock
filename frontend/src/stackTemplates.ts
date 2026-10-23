import { msg } from "./i18n";

/**
 * How a proxy gets its certificates. A DNS provider gives a wildcard certificate (names
 * stay out of public certificate logs) but needs its API token; the HTTP challenge works
 * with any domain and no API, one certificate per name, through port 80.
 */
export type CertChoice = "ovh" | "cloudflare" | "http" | "other";

export interface CertSetup {
  choice: CertChoice;
  /** The DNS provider's name as the proxy knows it; only typed for `other`. */
  provider: string;
}

export const CERT_CHOICES: { id: CertChoice; label: string; description: string }[] = [
  {
    id: "ovh",
    label: "OVH",
    description: msg("Wildcard certificate through the OVH API."),
  },
  {
    id: "cloudflare",
    label: "Cloudflare",
    description: msg("Wildcard certificate through the Cloudflare API."),
  },
  {
    id: "http",
    label: msg("HTTP challenge (any domain)"),
    description: msg(
      "No DNS API needed: one certificate per name, through port 80. The names appear in public certificate logs.",
    ),
  },
  {
    id: "other",
    label: msg("Other DNS provider"),
    description: msg(
      "Type your provider's name as the proxy knows it, then add its variables to the .env (Traefik) or its .ini file (SWAG).",
    ),
  },
];

export interface StackTemplate {
  id: string;
  label: string;
  description: string;
  /** Suggested stack name. */
  name: string;
  compose: (cert: CertSetup) => string;
  /** Written as the stack's .env after creation (admins only). `{domain}` is filled in. */
  env?: (cert: CertSetup) => string;
  /** The certificate choices of a proxy template, the first one by default. */
  certs?: CertChoice[];
}

const BLANK = `services:
  app:
    image: nginx:latest
    restart: unless-stopped
    ports:
      - "8080:80"
`;

const DNS_ENV: Record<string, string> = {
  ovh: `# OVH API token for the DNS challenge: https://eu.api.ovh.com/createToken/
# Rights: GET, POST, PUT and DELETE on /domain/zone/<domain>/*
OVH_ENDPOINT=ovh-eu
OVH_APPLICATION_KEY=
OVH_APPLICATION_SECRET=
OVH_CONSUMER_KEY=
`,
  cloudflare: `# Cloudflare API token with Zone / DNS / Edit on your zone:
# https://dash.cloudflare.com/profile/api-tokens
CF_DNS_API_TOKEN=
`,
};

/** Environment lines passing the DNS token to the proxy. */
function dnsEnvironment(choice: CertChoice): string {
  if (choice === "ovh") {
    return `      OVH_ENDPOINT: \${OVH_ENDPOINT:-ovh-eu}
      OVH_APPLICATION_KEY: \${OVH_APPLICATION_KEY}
      OVH_APPLICATION_SECRET: \${OVH_APPLICATION_SECRET}
      OVH_CONSUMER_KEY: \${OVH_CONSUMER_KEY}
`;
  }
  if (choice === "cloudflare") return "      CF_DNS_API_TOKEN: ${CF_DNS_API_TOKEN}\n";
  return "";
}

// The proxy sync (app/proxy_sync.py) turns the expose.* labels the Expose panel writes
// into the proxy's own config. {image} is DryDock's own image, filled in on creation.
function proxySync(proxy: string, output: string, extra = ""): string {
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
${extra}    volumes:
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

function commonHelp(cert: CertSetup): string {
  const certificates =
    cert.choice === "http"
      ? `# Certificates: one per name through the HTTP challenge, so forward port 80 to this
# host. No DNS API needed, but the names appear in public certificate logs.`
      : `# Certificates: one wildcard per domain through the DNS challenge (${cert.provider}): the
# service names never appear in public certificate logs.`;
  return `#
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
${certificates}`;
}

function traefik(cert: CertSetup): string {
  const resolver =
    cert.choice === "http"
      ? "      - --certificatesresolvers.le.acme.httpchallenge.entrypoint=web\n"
      : `      - --entrypoints.websecure.http.tls.domains[0].main=\${PROXY_DOMAIN}
      - --entrypoints.websecure.http.tls.domains[0].sans=*.\${PROXY_DOMAIN}
      - --certificatesresolvers.le.acme.dnschallenge.provider=${cert.provider}
      # Public resolvers: a local DNS that answers for the domain would fail the check.
      - --certificatesresolvers.le.acme.dnschallenge.resolvers=1.1.1.1:53,8.8.8.8:53
`;
  let environment = dnsEnvironment(cert.choice);
  environment = environment ? `    environment:\n${environment}` : "";
  // Any of lego's providers: its variables go in the .env, passed on as they are.
  const envFile =
    cert.choice === "other"
      ? "    # The DNS provider's variables (https://go-acme.github.io/lego/dns/).\n    env_file: .env\n"
      : "";
  return `# Reverse proxy: Traefik, for the services you expose from DryDock (Expose, beside the
# Compose editor). Fill in the .env tab, stop any other proxy on ports 80 and 443, then up.
${commonHelp(cert)}
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
      - --certificatesresolvers.le.acme.email=\${ACME_EMAIL}
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
${resolver}      # One line per request with the client IP, for fail2ban.
      - --accesslog=true
      - --accesslog.filepath=/logs/access.log
      - --api.dashboard=true
${environment}${envFile}    ports:
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
}

function swag(cert: CertSetup): string {
  return `# Reverse proxy: SWAG (nginx and certbot), for the services you expose from DryDock
# (Expose, beside the Compose editor). Fill in the .env tab, stop any other proxy on ports
# 80 and 443, then up. SWAG reads the DNS token from a file, not from .env: after the
# first up, fill in PROXY_DATA/swag/dns-conf/${cert.provider}.ini and restart swag.
${commonHelp(cert)}
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
      DNSPLUGIN: ${cert.provider}
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
}

// Caddy's caddy-dns module per DNS provider; the sync writes the matching acme_dns block.
const CADDY_MODULES: Record<string, string> = {
  ovh: "github.com/caddy-dns/ovh",
  cloudflare: "github.com/caddy-dns/cloudflare",
};

function caddy(cert: CertSetup): string {
  const module = CADDY_MODULES[cert.choice];
  const image = module
    ? `    build:
      dockerfile_inline: |
        FROM caddy:2-builder AS builder
        RUN xcaddy build --with ${module}
        FROM caddy:2
        COPY --from=builder /usr/bin/caddy /usr/bin/caddy
    image: caddy-${cert.choice}:local
`
    : "    image: caddy:2\n";
  const build = module
    ? `# Caddy's official image has no DNS modules, so the first up builds one with the
# ${cert.provider} module: a few minutes on a Pi.
`
    : "";
  return `# Reverse proxy: Caddy, for the services you expose from DryDock (Expose, beside the
# Compose editor). Fill in the .env tab, stop any other proxy on ports 80 and 443, then up.
${build}${commonHelp(cert)}
#
# proxy-sync writes the whole Caddyfile (PROXY_DATA/caddy/Caddyfile) and runs caddy
# reload, which refuses a bad config and keeps the running one. Caddy logs JSON: set
# the log format to JSON in DryDock's fail2ban jails (Host page).
services:
  caddy:
${image}    container_name: caddy
    restart: unless-stopped
    environment:
      ACME_EMAIL: \${ACME_EMAIL}
${dnsEnvironment(cert.choice)}    ports:
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

${proxySync("caddy", "/data/caddy", `      DNS_PROVIDER: ${cert.choice}\n`)}`;
}

/** The .env of a proxy stack: shared settings, then what the certificate needs. */
function proxyEnv(proxy: string) {
  return (cert: CertSetup): string => {
    let dns = DNS_ENV[cert.choice] ?? "";
    if (cert.choice === "http") {
      dns = "# Certificates through the HTTP challenge: forward port 80 to this host.\n";
    } else if (proxy === "swag") {
      // SWAG reads its token from dns-conf/<provider>.ini, never from the environment.
      dns = `# SWAG reads the DNS token from PROXY_DATA/swag/dns-conf/${cert.provider}.ini.\n`;
    } else if (cert.choice === "other") {
      dns = `# The variables of your DNS provider (${cert.provider}): https://go-acme.github.io/lego/dns/\n`;
    }
    return `# Host folder for certificates, config, allowlist and access log.
PROXY_DATA=/data/proxy
# Domain of the certificates: services get <name>.<domain>.
PROXY_DOMAIN={domain}
# Let's Encrypt account e-mail (expiry notices).
ACME_EMAIL=
# Private services allow these networks, your current public IP and these IPs (comma-separated).
LAN_RANGES=192.168.0.0/16
TRUSTED_IPS=
${dns}`;
  };
}

const PROXY_DESCRIPTION = msg(
  "HTTPS for the services you expose. Private services only answer your LAN, your public IP and trusted IPs.",
);

export const STACK_TEMPLATES: StackTemplate[] = [
  {
    id: "blank",
    label: msg("Blank"),
    description: msg("One nginx service to start from."),
    name: "",
    compose: () => BLANK,
  },
  {
    id: "traefik",
    label: msg("Traefik reverse proxy"),
    description: PROXY_DESCRIPTION,
    name: "traefik",
    compose: traefik,
    env: proxyEnv("traefik"),
    certs: ["ovh", "cloudflare", "http", "other"],
  },
  {
    id: "swag",
    label: msg("SWAG reverse proxy (nginx)"),
    description: PROXY_DESCRIPTION,
    name: "swag",
    compose: swag,
    env: proxyEnv("swag"),
    // SWAG's HTTP validation needs every name up front, so new services would need a
    // restart and a new certificate: DNS only.
    certs: ["ovh", "cloudflare", "other"],
  },
  {
    id: "caddy",
    label: msg("Caddy reverse proxy"),
    description: PROXY_DESCRIPTION,
    name: "caddy",
    compose: caddy,
    env: proxyEnv("caddy"),
    // Another DNS provider needs its module in the image and its block in the sync.
    certs: ["ovh", "cloudflare", "http"],
  },
];

/** The reverse proxy templates, for the Proxy page. */
export const PROXY_TEMPLATES = STACK_TEMPLATES.filter((template) => template.certs);

/** The certificate setup a template starts with. */
export function defaultCert(template: StackTemplate): CertSetup {
  const choice = template.certs?.[0] ?? "http";
  return { choice, provider: choice === "other" ? "" : choice };
}
