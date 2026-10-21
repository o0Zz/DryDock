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

// Matches proxy_service: "lan" for private services, "lan,wan" for public ones, and
// the shared network the Exposure panel attaches services to.
const TRAEFIK = `# Reverse proxy for the services you expose from DryDock (Exposure panel).
# Fill in the .env tab, then up. Stop any other proxy on ports 80 and 443 first.
#
# Entrypoints:
#   lan  :443   LAN and VPN only. Private services listen here.
#   wan  :8443  Forward the internet router's port 443 here. Public services listen here too.
# Do not forward 443 itself, nor open it over IPv6: private services would be reachable.
#
# One wildcard certificate (*.domain) through the OVH DNS challenge: service names
# never appear in public certificate logs.
services:
  traefik:
    image: traefik:v3
    restart: unless-stopped
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --providers.docker.network=proxy
      - --entrypoints.web.address=:80
      - --entrypoints.web.http.redirections.entrypoint.to=lan
      - --entrypoints.web.http.redirections.entrypoint.scheme=https
      - --entrypoints.lan.address=:443
      - --entrypoints.lan.http.tls.certresolver=le
      - --entrypoints.lan.http.tls.domains[0].main=\${PROXY_DOMAIN}
      - --entrypoints.lan.http.tls.domains[0].sans=*.\${PROXY_DOMAIN}
      - --entrypoints.wan.address=:8443
      - --entrypoints.wan.http.tls.certresolver=le
      - --entrypoints.wan.http.tls.domains[0].main=\${PROXY_DOMAIN}
      - --entrypoints.wan.http.tls.domains[0].sans=*.\${PROXY_DOMAIN}
      - --certificatesresolvers.le.acme.email=\${ACME_EMAIL}
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.dnschallenge.provider=ovh
      # Public resolvers: a local DNS that answers for the domain would fail the check.
      - --certificatesresolvers.le.acme.dnschallenge.resolvers=1.1.1.1:53,8.8.8.8:53
      - --api.dashboard=true
    environment:
      OVH_ENDPOINT: \${OVH_ENDPOINT:-ovh-eu}
      OVH_APPLICATION_KEY: \${OVH_APPLICATION_KEY}
      OVH_APPLICATION_SECRET: \${OVH_APPLICATION_SECRET}
      OVH_CONSUMER_KEY: \${OVH_CONSUMER_KEY}
    ports:
      - "80:80"
      - "443:443"
      - "8443:8443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
    networks:
      - proxy
    labels:
      # The dashboard has no login: LAN only.
      - traefik.enable=true
      - traefik.http.routers.traefik.rule=Host(\`traefik.\${PROXY_DOMAIN}\`)
      - traefik.http.routers.traefik.entrypoints=lan
      - traefik.http.routers.traefik.service=api@internal

networks:
  proxy:
    name: proxy
`;

const TRAEFIK_ENV = `# Domain of the wildcard certificate: services get <name>.<domain>.
PROXY_DOMAIN={domain}
# Let's Encrypt account e-mail (expiry notices).
ACME_EMAIL=
# OVH API token for the DNS challenge: https://eu.api.ovh.com/createToken/
# Rights: GET, POST, PUT and DELETE on /domain/zone/<domain>/*
OVH_ENDPOINT=ovh-eu
OVH_APPLICATION_KEY=
OVH_APPLICATION_SECRET=
OVH_CONSUMER_KEY=
`;

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
    description: msg(
      "HTTPS for the services you expose, with a wildcard certificate from the OVH DNS challenge. Private services stay on the LAN.",
    ),
    name: "traefik",
    compose: TRAEFIK,
    env: TRAEFIK_ENV,
  },
];
