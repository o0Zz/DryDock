/** Repository part of an image reference, with its tag and digest dropped. */
export function imageRepo(image: string): string {
  const ref = image.split("@")[0];
  // A colon before the last slash belongs to a registry port, not a tag.
  const slash = ref.lastIndexOf("/");
  const colon = ref.lastIndexOf(":");
  return colon > slash ? ref.slice(0, colon) : ref;
}

/**
 * Version label worth showing next to an image reference: hidden when the tag
 * already says it (`1.2.3` or `v1.2.3` for version `1.2.3`).
 */
export function extraVersion(image: string, version: string | null): string | null {
  if (!version) return null;
  const ref = image.split("@")[0];
  const tag = ref.length > imageRepo(ref).length ? ref.slice(imageRepo(ref).length + 1) : "latest";
  return tag.replace(/^v/, "") === version.replace(/^v/, "") ? null : version;
}

/**
 * Point every `image: <image>` line of a Compose file at `tag`, keeping quotes
 * and trailing comments. Returns how many lines changed (0 = not found).
 */
export function retagImage(
  content: string,
  image: string,
  tag: string,
): { content: string; count: number } {
  const escaped = image.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const line = new RegExp(`^(\\s*image:\\s*)(["']?)${escaped}\\2(\\s*(?:#.*)?)$`, "gm");
  let count = 0;
  const next = content.replace(line, (_match, lead: string, quote: string, tail: string) => {
    count += 1;
    return `${lead}${quote}${imageRepo(image)}:${tag}${quote}${tail}`;
  });
  return { content: next, count };
}
