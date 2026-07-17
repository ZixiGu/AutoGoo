/**
 * UI helpers — wraps ctx.ui.select to work with string arrays (Pi's API).
 * Maps selected label back to value.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { SelectOption } from "../types.js";

/**
 * Show a select dialog with string labels, return the matching value.
 * Pi's ctx.ui.select only accepts string[].
 */
export async function uiSelect(
  ctx: ExtensionContext,
  header: string,
  options: SelectOption[],
): Promise<string | null> {
  const labels = options.map((o) => o.label);
  const choice = await ctx.ui.select(header, labels);
  if (!choice) return null;
  const found = options.find((o) => o.label === choice);
  return found?.value ?? choice;
}

/**
 * Show a confirm dialog, return boolean.
 */
export async function uiConfirm(
  ctx: ExtensionContext,
  header: string,
  question: string,
): Promise<boolean> {
  const result = await ctx.ui.confirm(header, question);
  return !!result;
}

/**
 * Show an input dialog, return string or null.
 */
export async function uiInput(
  ctx: ExtensionContext,
  question: string,
  defaultValue?: string,
): Promise<string | null> {
  const result = await ctx.ui.input(question, defaultValue ?? "");
  return result || null;
}
