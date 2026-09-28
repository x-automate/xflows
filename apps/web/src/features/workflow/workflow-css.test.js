import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { XFLOWS_CATALOG } from "./catalog/catalog-meta.js";
import { portsForNode } from "./catalog/port-model.js";

/**
 * The stylesheet, read through the cascade rather than by eye.
 *
 * `.wf-port-error-out` used to be declared above two later `.wf-port` blocks of
 * equal specificity, so its offset, its border and its background all lost —
 * the error bubble rendered black-on-white directly under the data bubble and
 * nothing in the test suite noticed. These tests resolve the cascade the way a
 * browser would, so a rule that quietly overrides the port model fails here.
 */

const CSS = readFileSync(new URL("./workflow.css", import.meta.url), "utf8");

function parseDeclarations(body) {
  const declarations = {};
  for (const part of body.split(";")) {
    const at = part.indexOf(":");
    if (at === -1) continue;
    const property = part.slice(0, at).trim();
    const value = part.slice(at + 1).trim();
    if (property && value) declarations[property] = value;
  }
  return declarations;
}

/** Every top-level rule, in source order, one entry per comma-separated selector. */
function parseRules(css) {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];
  let index = 0;
  while (index < source.length) {
    const open = source.indexOf("{", index);
    if (open === -1) break;
    const prelude = source.slice(index, open).trim();
    let depth = 1;
    let cursor = open + 1;
    while (cursor < source.length && depth > 0) {
      if (source[cursor] === "{") depth += 1;
      else if (source[cursor] === "}") depth -= 1;
      cursor += 1;
    }
    if (!prelude.startsWith("@")) {
      const declarations = parseDeclarations(source.slice(open + 1, cursor - 1));
      for (const selector of prelude.split(",").map((item) => item.trim())) {
        if (selector) rules.push({ selector, declarations });
      }
    }
    index = cursor;
  }
  return rules;
}

const RULES = parseRules(CSS);

const isPlainClassChain = (selector) => /^(\.[A-Za-z0-9_-]+)+$/.test(selector);
const classesIn = (selector) => selector.split(".").filter(Boolean);

/** What a browser would end up applying to an element with these classes. */
function effectiveStyle(classes) {
  const winners = {};
  RULES.forEach((rule, order) => {
    if (!isPlainClassChain(rule.selector)) return;
    const selectorClasses = classesIn(rule.selector);
    if (!selectorClasses.every((name) => classes.includes(name))) return;
    const specificity = selectorClasses.length;
    for (const [property, value] of Object.entries(rule.declarations)) {
      const current = winners[property];
      if (!current || specificity >= current.specificity) {
        winners[property] = { value, specificity, order };
      }
    }
  });
  return Object.fromEntries(
    Object.entries(winners).map(([property, win]) => [property, win.value])
  );
}

const PORT_CLASSES = [
  "wf-port-in",
  "wf-port-out",
  "wf-port-error-out",
  "wf-port-config-out",
  "wf-port-config-in",
];

describe("port styling survives the cascade", () => {
  it("keeps the error bubble red instead of letting a later .wf-port win", () => {
    const style = effectiveStyle(["wf-port", "wf-port-error-out"]);
    expect(style["border-color"]).toBe("#dc2626");
    expect(style.background).toBe("#fee2e2");
  });

  it("keeps the data bubble in the neutral data colour", () => {
    const style = effectiveStyle(["wf-port", "wf-port-out"]);
    expect(style["border-color"]).toBe("#111827");
    expect(style.background).toBe("#fff");
  });

  it("keeps the config bubbles in the config colour", () => {
    for (const name of ["wf-port-config-out", "wf-port-config-in"]) {
      const style = effectiveStyle(["wf-port", name]);
      expect(style["border-color"], name).toBe("#c2410c");
      expect(style.background, name).toBe("#fff7ed");
    }
  });

  it("centres every bubble on the position the port model hands it", () => {
    for (const name of PORT_CLASSES) {
      const style = effectiveStyle(["wf-port", name]);
      expect(style.position, name).toBe("absolute");
      expect(style.transform, name).toBe("translate(-50%, -50%)");
    }
  });

  it("leaves port placement to the port model, never to an offset here", () => {
    const offsets = ["top", "right", "bottom", "left", "inset", "margin"];
    for (const rule of RULES) {
      const bubbleClasses = ["wf-port", ...PORT_CLASSES];
      if (!classesIn(rule.selector).some((name) => bubbleClasses.includes(name))) continue;
      for (const property of offsets) {
        expect(
          rule.declarations[property],
          `${rule.selector} sets "${property}" — that moves the bubble away from its wire`
        ).toBeUndefined();
      }
    }
  });

  it("lets the pointer through the port layer but not through a port", () => {
    expect(effectiveStyle(["wf-ports-layer"])["pointer-events"]).toBe("none");
    expect(effectiveStyle(["wf-port"])["pointer-events"]).toBe("auto");
  });

  it("draws error edges dashed and data edges solid", () => {
    expect(effectiveStyle(["wf-edge", "error"])["stroke-dasharray"]).toBe("6 4");
    expect(effectiveStyle(["wf-edge"])["stroke-dasharray"]).toBeUndefined();
    expect(effectiveStyle(["wf-edge", "error"]).stroke).toBe("#dc2626");
  });

  it("has a rule for every port class the canvas renders", () => {
    const rendered = new Set();
    for (const component of XFLOWS_CATALOG) {
      const node = { id: "n", componentId: component.id, x: 0, y: 0 };
      for (const port of portsForNode(node)) rendered.add(port.className);
    }
    const styled = new Set(
      RULES.flatMap((rule) => classesIn(rule.selector)).filter((name) =>
        name.startsWith("wf-port-")
      )
    );
    for (const className of rendered) {
      expect(styled.has(className), `${className} has no rule in workflow.css`).toBe(true);
    }
    expect([...rendered].sort()).toEqual(PORT_CLASSES.slice().sort());
  });
});
