import { yaml } from "@codemirror/lang-yaml";
import CodeMirror from "@uiw/react-codemirror";

/** Compose-file editor: YAML syntax highlighting, line numbers, bracket matching.
 * `plain` drops the YAML mode, for `.env` files. */
export default function YamlEditor({
  value,
  onChange,
  height = "480px",
  plain = false,
}: {
  value: string;
  onChange: (next: string) => void;
  height?: string;
  plain?: boolean;
}) {
  return (
    <div className="yaml-editor">
      <CodeMirror
        value={value}
        height={height}
        extensions={plain ? [] : [yaml()]}
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
