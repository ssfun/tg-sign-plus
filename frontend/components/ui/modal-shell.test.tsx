import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ModalShell } from "./modal-shell";

afterEach(cleanup);
it("labels the dialog, traps focus, and restores it when closed", () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{ width: 10, height: 10 }] as unknown as DOMRectList);
    function Example() {
        const [open, setOpen] = useState(false);
        return <><button onClick={() => setOpen(true)}>Open editor</button>
            <ModalShell open={open} title="Edit task" description="Task fields" onClose={() => setOpen(false)}>
                <input aria-label="Task name" /><button>Save</button>
            </ModalShell></>;
    }
    render(<Example />);
    const opener = screen.getByText("Open editor");
    opener.focus(); fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Edit task" });
    expect(document.activeElement).toBe(dialog);
    screen.getByText("Save").focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByLabelText("Close modal"));
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(screen.getByText("Save"));
    opener.focus();
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
    expect(document.body.style.overflow).toBe("");
});
