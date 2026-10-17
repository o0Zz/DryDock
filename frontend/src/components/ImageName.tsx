import { extraVersion } from "../imageRef";

/** An image reference, plus the version its label declares when the tag hides it. */
export default function ImageName({ image, version }: { image: string; version: string | null }) {
  const extra = extraVersion(image, version);
  return (
    <>
      {image}
      {extra && (
        <span className="muted" title="From the image's org.opencontainers.image.version label">
          {" "}
          ({extra})
        </span>
      )}
    </>
  );
}
