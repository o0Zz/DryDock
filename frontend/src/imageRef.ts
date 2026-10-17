/** Repository part of an image reference, with its tag and digest dropped. */
export function imageRepo(image: string): string {
  const nameAndTag = image.split("@")[0];
  // A colon before the last slash belongs to a registry port, not a tag.
  const lastSlash = nameAndTag.lastIndexOf("/");
  const lastColon = nameAndTag.lastIndexOf(":");
  return lastColon > lastSlash ? nameAndTag.slice(0, lastColon) : nameAndTag;
}

/**
 * Version label worth showing next to an image reference: hidden when the tag
 * already says it (`1.2.3` or `v1.2.3` for version `1.2.3`).
 */
export function extraVersion(image: string, version: string | null): string | null {
  if (!version) return null;
  const nameAndTag = image.split("@")[0];
  const repository = imageRepo(nameAndTag);
  const tag =
    nameAndTag.length > repository.length ? nameAndTag.slice(repository.length + 1) : "latest";
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
  const escapedImage = image.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const imageLine = new RegExp(`^(\\s*image:\\s*)(["']?)${escapedImage}\\2(\\s*(?:#.*)?)$`, "gm");
  let count = 0;
  const retagged = content.replace(
    imageLine,
    (_match, prefix: string, quote: string, suffix: string) => {
      count += 1;
      return `${prefix}${quote}${imageRepo(image)}:${tag}${quote}${suffix}`;
    },
  );
  return { content: retagged, count };
}
