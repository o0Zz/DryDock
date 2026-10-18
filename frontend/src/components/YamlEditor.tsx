import { yaml } from "@codemirror/lang-yaml";
import CodeMirror, { keymap, Prec } from "@uiw/react-codemirror";
import { useEffect, useMemo, useRef } from "react";

/** Compose-file editor: YAML syntax highlighting, line numbers, bracket matching.
 * `plain` drops the YAML mode, for `.env` files. `onSave` runs on Ctrl+S / Cmd+S. */
export default function YamlEditor({
  value,
  onChange,
  onSave,
  height = "480px",
  plain = false,
}: {
  value: string;
  onChange: (next: string) => void;
  onSave?: () => void;
  height?: string;
  plain?: boolean;
}) {
  // The keymap is built once; the ref hands it the latest handler and its state.
  const onSaveRef = useRef(onSave);
  useEffect(() => {
    onSaveRef.current = onSave;
  }, [onSave]);

  const extensions = useMemo(
    () => [
      ...(plain ? [] : [yaml()]),
      // Highest precedence, so the browser's "Save page" dialog never opens from the editor.
      Prec.highest(
        keymap.of([
          {
            key: "Mod-s",
            preventDefault: true,
            run: () => {
              onSaveRef.current?.();
              return true;
            },
          },
        ]),
      ),
    ],
    [plain],
  );

  return (
    <div className="yaml-editor">
      <CodeMirror
        value={value}
        height={height}
        extensions={extensions}
        onChange={onChange}
        basicSetup={{
          lineNumbers: true,
          highlightActiveLine: true,
          bracketMatching: true,
          // Compose files are indentation-sensitive; autocompleting brackets
          // inside YAML does more harm than good.
          closeBrackets: false,
          autocompletion: false,
        }}
      />
    </div>
  );
}
