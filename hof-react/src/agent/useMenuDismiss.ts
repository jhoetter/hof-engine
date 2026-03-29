import { useEffect, type RefObject } from "react";

/**
 * Dismisses a menu when clicking outside or pressing Escape.
 * @param isOpen - Whether the menu is currently open
 * @param setIsOpen - Setter to close the menu
 * @param containerRef - Ref to the menu container element
 */
export function useMenuDismiss(
  isOpen: boolean,
  setIsOpen: (open: boolean) => void,
  containerRef: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const onDocDown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen, setIsOpen, containerRef]);
}
