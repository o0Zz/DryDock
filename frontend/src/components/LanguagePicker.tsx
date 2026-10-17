import { Languages } from "lucide-react";
import { LANGUAGES, useI18n, type Language } from "../i18n";

/** Language switch; the choice is kept in this browser. */
export default function LanguagePicker() {
  const { language, setLanguage, t } = useI18n();
  return (
    <label className="language-picker" title={t("Language")}>
      <Languages size={15} />
      <select
        value={language}
        aria-label={t("Language")}
        onChange={(event) => setLanguage(event.target.value as Language)}
      >
        {LANGUAGES.map((option) => (
          <option key={option.code} value={option.code}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
