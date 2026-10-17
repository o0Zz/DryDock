import { extraVersion } from "../imageRef";

/** An image reference, plus the version its label declares when the tag hides it. */
export default function ImageName({ image, version }: { image: string; version: string | null }) {
  const labelVersion = extraVersion(image, version);
  return (
    <>
      {image}
      {labelVersion && (
        <span className="muted" title="From the image's org.opencontainers.image.version label">
          {" "}
          ({labelVersion})
        </span>
      )}
    </>
  );
}
