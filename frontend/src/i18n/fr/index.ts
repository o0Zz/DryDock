// Every JSON file in this folder is one area of the UI. They are merged into one
// dictionary: English text -> French text. Missing keys fall back to English.
const areas = import.meta.glob<Record<string, string>>("./*.json", {
  eager: true,
  import: "default",
});

const fr: Record<string, string> = Object.assign({}, ...Object.values(areas));

export default fr;
