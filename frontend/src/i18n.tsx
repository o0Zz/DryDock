import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import fr from "./i18n/fr";

/**
 * UI translations without a library.
 *
 * The English text is the key: `t("Delete volume")`. Other languages map it to
 * their text in `i18n/<lang>/`, and anything missing falls back to English, so
 * an untranslated string still reads fine. `{name}` placeholders are filled
 * from the second argument. Text built outside a component (tab lists, option
 * tables) is marked with `msg("...")` and translated where it is shown, so
 * `npm run i18n:check` finds every key either way.
 *
 * Messages from the API (errors, job labels) stay in English.
 */

export type Language = "en" | "fr";

export const LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
];

const DICTIONARIES: Record<Language, Record<string, string>> = { en: {}, fr };

const STORAGE_KEY = "drydock.language";

export type Vars = Record<string, string | number>;
export type Translate = (text: string, vars?: Vars) => string;

function initialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && saved in DICTIONARIES) return saved as Language;
  } catch {
    // storage blocked: fall back to the browser language
  }
  return navigator.language.toLowerCase().startsWith("fr") ? "fr" : "en";
}

// Module-level copy for helpers outside React (format.ts, confirm dialogs built in plain functions).
let current: Language = initialLanguage();

export function translate(text: string, vars?: Vars): string {
  const translated = DICTIONARIES[current][text] ?? text;
  if (!vars) return translated;
  return translated.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

/** Marks text for translation where it is defined; `t()` translates it where it is shown. */
export function msg(text: string): string {
  return text;
}

interface I18nValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: Translate;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(current);

  const setLanguage = useCallback((next: Language): void => {
    current = next;
    setLanguageState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // not persisted; the choice still holds for this visit
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  // A new function per language, so components using `t` in deps re-run on a switch.
  const t = useCallback<Translate>((text, vars) => translate(text, vars), [language]);

  return (
    <I18nContext.Provider value={{ language, setLanguage, t }}>{children}</I18nContext.Provider>
  );
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside <I18nProvider>");
  return value;
}

/** The translate function; re-renders the component when the language changes. */
export function useT(): Translate {
  return useI18n().t;
}
