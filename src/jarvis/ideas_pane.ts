/** A compact, read-only ranking beside the editor. /ideas or Alt+I toggles it. */
import { stripVTControlCharacters } from "node:util";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

interface Idea {
	title: string;
	status: string;
	elo: number;
}

// Database text and subprocess errors must never inject terminal escapes or extra rows.
const oneLine = (text: string) => stripVTControlCharacters(text).replace(/[\x00-\x1f\x7f-\x9f]+/g, " ").trim();

export default function ideasPane(pi: ExtensionAPI) {
	const widget = "jarvis-ideas";
	let visible = true;
	let generation = 0;

	async function refresh(ctx: ExtensionContext) {
		if (ctx.mode !== "tui" || !visible) return;
		const request = ++generation;
		try {
			// Inherit JARVIS_PROJECT, JARVIS_DB and PATH from `jarvis chat`.
			const result = await pi.exec("jarvis", ["ideas", "list", "--ranked", "--json"], { timeout: 10000 });
			if (result.code !== 0) throw new Error(result.stderr || result.stdout || "jarvis failed");
			const rows: unknown = JSON.parse(result.stdout);
			if (!Array.isArray(rows) || rows.some((r) => !r || typeof r.title !== "string" ||
				typeof r.status !== "string" || typeof r.elo !== "number" || !Number.isFinite(r.elo))) {
				throw new Error("invalid ranked ideas response");
			}
			if (request !== generation || !visible) return;
			const ideas = rows as Idea[];
			ctx.ui.setWidget(widget, (_tui, theme) => ({
				render(width: number) {
					const lines = [theme.fg("accent", theme.bold("Ideas")) + theme.fg("dim", " · /ideas or Alt+I to hide")];
					for (const [i, idea] of ideas.slice(0, 8).entries()) {
						const prefix = `${i + 1}. [${oneLine(idea.status)}] `;
						const suffix = ` · Elo ${Math.round(idea.elo)}`;
						const title = truncateToWidth(oneLine(idea.title), Math.max(0, width - visibleWidth(prefix + suffix)));
						lines.push(theme.fg("muted", prefix) + title + theme.fg("dim", suffix));
					}
					if (!ideas.length) lines.push(theme.fg("muted", "(no ideas)"));
					if (ideas.length > 8) lines.push(theme.fg("muted", `+${ideas.length - 8} more`));
					return lines.map((line) => truncateToWidth(line, width));
				},
				invalidate() {},
			}));
		} catch (error) {
			if (request !== generation || !visible) return;
			const message = oneLine(error instanceof Error ? error.message : String(error));
			ctx.ui.setWidget(widget, (_tui, theme) => ({
				render: (width: number) => [truncateToWidth(theme.fg("warning", `Ideas unavailable: ${message}`), width)],
				invalidate() {},
			}));
		}
	}

	async function toggle(ctx: ExtensionContext) {
		if (ctx.mode !== "tui") return;
		visible = !visible;
		++generation; // An older refresh must not resurrect a hidden widget.
		if (visible) await refresh(ctx);
		else ctx.ui.setWidget(widget, undefined);
	}

	pi.registerCommand("ideas", { description: "Toggle the ranked ideas pane", handler: async (_args, ctx) => toggle(ctx) });
	// Alt+I is unassigned in Pi's default editor/application keybindings.
	pi.registerShortcut("alt+i", { description: "Toggle the ranked ideas pane", handler: toggle });
	pi.on("session_start", async (_event, ctx) => refresh(ctx));
	// Refresh after every completed turn, including intermediate tool turns.
	pi.on("turn_end", async (_event, ctx) => refresh(ctx));
	pi.on("session_shutdown", (_event, ctx) => {
		++generation;
		if (ctx.mode === "tui") ctx.ui.setWidget(widget, undefined);
	});
}
