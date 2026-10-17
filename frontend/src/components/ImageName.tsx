import { useT } from "../i18n";
import { extraVersion } from "../imageRef";

/** An image reference, plus the version its label declares when the tag hides it. */
export default function ImageName({ image, version }: { image: string; version: string | null }) {
  const t = useT();
  const labelVersion = extraVersion(image, version);
  return (
    <>
      {image}
      {labelVersion && (
        <span className="muted" title={t("From the image's {label} label", {
            label: "org.opencontainers.image.version",
          })}>
          {" "}
          ({labelVersion})
        </span>
      )}
    </>
  );
}
