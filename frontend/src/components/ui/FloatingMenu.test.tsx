// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useRef } from "react";
import FloatingMenu from "./FloatingMenu";

let container: HTMLDivElement;
let root: Root;

function mount(children: React.ReactNode) {
  act(() => {
    root.render(<div id="host">{children}</div>);
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function Harness({ open }: { open: boolean }) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={anchorRef}>anchor</button>
      <FloatingMenu open={open} anchorRef={anchorRef} placement="bottom-start">
        <div>menu-content</div>
      </FloatingMenu>
    </>
  );
}

describe("FloatingMenu", () => {
  it("renders the menu into document.body, outside any overflow-clipping host", () => {
    mount(<Harness open />);
    const host = document.getElementById("host")!;
    // The portal wrapper is a direct child of body carrying the fixed class.
    const menu = document.querySelector("body > .fixed") as HTMLElement | null;
    expect(menu).toBeTruthy();
    expect(menu!.textContent).toContain("menu-content");
    // The menu must not be a DOM descendant of the component host, so
    // overflow-hidden / overflow-x-auto ancestors can never clip it.
    expect(host.contains(menu!)).toBe(false);
  });

  it("renders nothing when closed", () => {
    mount(<Harness open={false} />);
    expect(document.querySelector("body > .fixed")).toBeNull();
  });
});
