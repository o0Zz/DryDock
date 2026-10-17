import { AlertTriangle, HelpCircle, type LucideIcon } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

export interface ConfirmOptions {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** "danger" for anything that deletes or removes. */
  tone?: "primary" | "danger";
  icon?: LucideIcon;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

/**
 * In-app replacement for `window.confirm`: `await confirm({...})` resolves to
 * true when the user accepts. Built on <dialog>, so focus trapping, Escape and
 * the backdrop come from the browser.
 */
export function useConfirm(): Confirm {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return confirm;
}

interface Pending extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  const confirm = useCallback<Confirm>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending((prev) => {
          // A second request replaces the first; the first counts as cancelled.
          prev?.resolve(false);
          return { ...options, resolve };
        });
      }),
    [],
  );

  useEffect(() => {
    const el = dialog.current;
    if (pending && el && !el.open) el.showModal();
  }, [pending]);

  const settle = useCallback(
    (ok: boolean) => {
      pending?.resolve(ok);
      setPending(null);
      dialog.current?.close();
    },
    [pending],
  );

  const tone = pending?.tone ?? "primary";
  const Icon = pending?.icon ?? (tone === "danger" ? AlertTriangle : HelpCircle);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <dialog
        ref={dialog}
        className={`confirm-dialog ${tone}`}
        aria-labelledby="confirm-title"
        // Escape fires "cancel"; treat it like the Cancel button.
        onCancel={(e) => {
          e.preventDefault();
          settle(false);
        }}
        // A click on the backdrop lands on the <dialog> element itself.
        onClick={(e) => e.target === e.currentTarget && settle(false)}
      >
        {pending && (
          <div className="confirm-body">
            <div className="confirm-icon">
              <Icon size={22} />
            </div>
            <div className="confirm-content">
              <h3 id="confirm-title">{pending.title}</h3>
              {pending.message && <div className="confirm-message">{pending.message}</div>}
              <div className="confirm-actions">
                {/* Enter should never delete by accident: danger focuses Cancel. */}
                <button
                  type="button"
                  className="secondary"
                  autoFocus={tone === "danger"}
                  onClick={() => settle(false)}
                >
                  {pending.cancelLabel ?? "Cancel"}
                </button>
                <button
                  type="button"
                  className={tone === "danger" ? "danger" : undefined}
                  autoFocus={tone !== "danger"}
                  onClick={() => settle(true)}
                >
                  {pending.confirmLabel ?? "Confirm"}
                </button>
              </div>
            </div>
          </div>
        )}
      </dialog>
    </ConfirmContext.Provider>
  );
}
