"use client";

import { toast as toastManager } from "./toast";

type ToastOptions = {
  title?: string;
  description?: string;
  variant?: "default" | "destructive";
};

/**
 * Compatibility hook for call sites written against the classic
 * shadcn `use-toast` API: `const { toast } = useToast()`.
 * Maps `variant: "destructive"` onto the base-ui toast `type: "error"`.
 * Uses the module-level toast manager (the same one `<Toaster />`
 * subscribes to), so it never depends on provider context during render.
 */
export function useToast() {
  const toast = (opts: ToastOptions) =>
    toastManager.add({
      title: opts.title,
      description: opts.description,
      type: opts.variant === "destructive" ? "error" : "success",
    });

  return { toast };
}
