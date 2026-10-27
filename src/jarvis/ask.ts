/**
 * `ask`: a pi tool that shows the researcher one card at a time and lets them answer each with a key,
 * the arrow keys or the mouse, add a note anywhere, and submit from a summary page.
 *
 * With `choices`, every card gets one of them (idea verdicts). Without, the researcher picks one card
 * (e.g. which open problem to work on). Either way there is a free-text note per card and one overall.
 */

import { getMarkdownTheme, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	Editor,
	type EditorTheme,
	Key,
	Markdown,
	matchesKey,
	Text,
	truncateToWidth,
	type TuiMouseEvent,
	visibleWidth,
	wrapTextWithAnsi,
} from "@earendil-works/pi-tui";
import { Type } from "typebox";

interface Card {
	title: string;
	body?: string;
}

interface Choice {
	key: string;
	label: string;
}

interface Answers {
	question: string;
	cards: Card[];
	choices: Choice[];
	picking: boolean;
	chosen: (number | undefined)[]; // choice index per card
	notes: string[]; // per card
	note: string; // overall
	dismissed: boolean;
}

const Params = Type.Object({
	question: Type.String({ description: "One line shown above the cards, e.g. 'Which of these ideas do you want?'" }),
	cards: Type.Array(
		Type.Object({
			title: Type.String({ description: "Short title, e.g. '1. Lamarckian inheritance by node id'" }),
			body: Type.Optional(Type.String({ description: "Markdown, a few lines: summary, evidence, cheapest test" })),
		}),
		{ minItems: 1 },
	),
	choices: Type.Optional(
		Type.Array(
			Type.Object({
				key: Type.Optional(Type.String({ description: "One lowercase letter, e.g. 'a'" })),
				label: Type.String(),
			}),
			{ description: "Give each card one of these. Omit to let the user pick a single card instead." },
		),
	),
});

const NOTE_KEY = "n";

/** Turns the answers into the text the model reads. */
function summarize(a: Answers): string {
	const out: string[] = [];
	const noteOf = (i: number) => (a.notes[i] ? ` (note: ${a.notes[i]})` : "");
	if (a.picking) {
		const picked = a.chosen.findIndex((c) => c !== undefined);
		out.push(picked < 0 ? "Picked: none" : `Picked: ${a.cards[picked].title}${noteOf(picked)}`);
		a.cards.forEach((c, i) => i !== picked && a.notes[i] && out.push(`Note on ${c.title}: ${a.notes[i]}`));
	} else {
		a.cards.forEach((c, i) => {
			const ch = a.chosen[i] === undefined ? undefined : a.choices[a.chosen[i]!];
			out.push(`${c.title}: ${ch ? `(${ch.key}) ${ch.label}` : "no choice"}${noteOf(i)}`);
		});
	}
	if (a.note) out.push(`Overall note: ${a.note}`);
	if (a.dismissed) out.push("(The user closed the cards with Esc; treat unanswered cards as undecided.)");
	return out.join("\n");
}

export default function ask(pi: ExtensionAPI) {
	pi.registerTool({
		name: "ask",
		label: "Ask",
		description:
			"Ask the researcher to choose, showing one card at a time. With `choices`, they give each card one choice " +
			"(e.g. approve/reject/elaborate/ground for ideas); without, they pick one card. They can add a note to " +
			"any card and an overall note. Returns their answers as text. Use this instead of a typed reply menu.",
		parameters: Params,
		exposure: "model-only",

		async execute(_id, params, _signal, _onUpdate, ctx) {
			if (ctx.mode !== "tui") throw new Error("ask needs the interactive UI; ask in plain text instead");
			const picking = !params.choices?.length;
			const used = new Set([NOTE_KEY]);
			const choices: Choice[] = (params.choices?.length ? params.choices : [{ label: "Pick this one" }]).map((c, i) => {
				let key = (c.key ?? "").toLowerCase().slice(0, 1);
				if (!/[a-z]/.test(key) || used.has(key)) key = String(i + 1); // digits always work too
				used.add(key);
				return { key, label: c.label };
			});
			const cards: Card[] = params.cards;
			const answers = await ctx.ui.custom<Answers>((tui, theme, _kb, done) =>
				cardDeck(tui, theme, done, { question: params.question, cards, choices, picking }),
			);
			return { content: [{ type: "text", text: summarize(answers) }], details: answers };
		},

		renderCall(args, theme) {
			const n = (args.cards as Card[] | undefined)?.length ?? 0;
			return new Text(
				theme.fg("toolTitle", theme.bold("ask ")) + theme.fg("muted", `${args.question ?? ""} (${n} card${n === 1 ? "" : "s"})`),
				0,
				0,
			);
		},

		renderResult(result, _options, theme) {
			const a = result.details as Answers | undefined;
			if (!a) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			return new Text(
				summarize(a)
					.split("\n")
					.map((l) => theme.fg("success", "✓ ") + l)
					.join("\n"),
				0,
				0,
			);
		},
	});
}

type Action =
	| { kind: "goto"; page: number }
	| { kind: "choose"; choice: number }
	| { kind: "note" }
	| { kind: "submit" };

// A clickable span on a rendered line; no x range means the whole line.
interface Hit {
	line: number;
	x0?: number;
	x1?: number;
	action: Action;
}

function cardDeck(
	tui: any,
	theme: any,
	done: (a: Answers) => void,
	init: { question: string; cards: Card[]; choices: Choice[]; picking: boolean },
) {
	const { question, cards, choices, picking } = init;
	const n = cards.length;
	const chosen: (number | undefined)[] = cards.map(() => undefined);
	const notes: string[] = cards.map(() => "");
	let note = "";
	let page = 0; // 0..n-1 are cards, n is the submit page
	let cursor = 0; // highlighted row on the page
	let editing = false; // the note editor is open for this page
	let cached: string[] | undefined;
	let cachedWidth = 0;
	let hits: Hit[] = [];

	const editorTheme: EditorTheme = {
		borderColor: (s) => theme.fg("accent", s),
		selectList: {
			selectedPrefix: (t) => theme.fg("accent", t),
			selectedText: (t) => theme.fg("accent", t),
			description: (t) => theme.fg("muted", t),
			scrollInfo: (t) => theme.fg("dim", t),
			noMatch: (t) => theme.fg("warning", t),
		},
	};
	const editor = new Editor(tui, editorTheme);
	editor.onSubmit = (value) => {
		if (page === n) note = value.trim();
		else notes[page] = value.trim();
		editing = false;
		refresh();
	};

	// Rows on a card: the choices, then the note. On the submit page: one per card, the note, Submit.
	const rowCount = () => (page < n ? choices.length + 1 : n + 2);
	const finish = (dismissed: boolean) =>
		done({ question, cards, choices, picking, chosen, notes, note, dismissed });

	function refresh() {
		cached = undefined;
		tui.requestRender();
	}

	function goto(p: number) {
		page = Math.max(0, Math.min(n, p));
		editing = false;
		const c = page < n ? chosen[page] : undefined;
		cursor = page === n ? n + 1 : (c ?? 0);
		refresh();
	}

	function choose(i: number) {
		if (chosen[page] === i) {
			chosen[page] = undefined; // choosing again clears it
			return refresh();
		}
		if (picking) chosen.fill(undefined);
		chosen[page] = i;
		goto(picking ? n : page + 1);
	}

	function openNote() {
		editing = true;
		editor.setText(page === n ? note : notes[page]);
		refresh();
	}

	function act(a: Action) {
		if (a.kind === "goto") goto(a.page);
		else if (a.kind === "choose") choose(a.choice);
		else if (a.kind === "note") openNote();
		else finish(false);
	}

	function activateRow() {
		if (page < n) return act(cursor < choices.length ? { kind: "choose", choice: cursor } : { kind: "note" });
		if (cursor < n) return goto(cursor);
		act(cursor === n ? { kind: "note" } : { kind: "submit" });
	}

	function handleInput(data: string) {
		if (editing) {
			if (matchesKey(data, Key.escape)) {
				editing = false;
				return refresh();
			}
			editor.handleInput(data);
			return refresh();
		}
		if (matchesKey(data, Key.escape)) return finish(true);
		if (matchesKey(data, Key.right) || matchesKey(data, Key.tab)) return goto(page + 1);
		if (matchesKey(data, Key.left) || matchesKey(data, Key.shift("tab"))) return goto(page - 1);
		if (matchesKey(data, Key.up)) {
			cursor = Math.max(0, cursor - 1);
			return refresh();
		}
		if (matchesKey(data, Key.down)) {
			cursor = Math.min(rowCount() - 1, cursor + 1);
			return refresh();
		}
		if (matchesKey(data, Key.enter) || matchesKey(data, Key.space)) return activateRow();
		if (data === NOTE_KEY) return openNote();
		if (page < n) {
			const i = choices.findIndex((c, j) => data === c.key || data === String(j + 1));
			if (i >= 0) return choose(i);
		}
	}

	function handleMouse(e: TuiMouseEvent) {
		if (e.type !== "click" || e.button !== "left" || editing) return undefined;
		const hit = hits.find((h) => h.line === e.y && (h.x0 === undefined || (e.x >= h.x0 && e.x < h.x1!)));
		if (!hit) return undefined;
		act(hit.action);
		return { handled: true };
	}

	function render(width: number): string[] {
		if (cached && cachedWidth === width) return cached;
		const w = Math.max(20, width);
		const lines: string[] = [];
		hits = [];
		const push = (s: string, action?: Action) => {
			if (action) hits.push({ line: lines.length, action });
			lines.push(truncateToWidth(s, w));
		};
		const row = (i: number, text: string, action: Action) => {
			const on = i === cursor && !editing;
			push((on ? theme.fg("accent", " ▸ ") : "   ") + (on ? theme.bold(text) : text), action);
		};

		push(theme.fg("accent", "─".repeat(w)));
		push(" " + theme.bold(question));

		// Tab strip: ‹  one slot per card (its chosen key, or ·)  Submit  ›
		let strip = " ";
		const stripHits: Hit[] = [];
		const slot = (label: string, active: boolean, color: string, p: number) => {
			const text = ` ${label} `;
			const x0 = visibleWidth(strip);
			strip += active ? theme.bg("selectedBg", theme.fg("text", text)) : theme.fg(color, text);
			stripHits.push({ line: lines.length, x0, x1: x0 + visibleWidth(text), action: { kind: "goto", page: p } });
			strip += " ";
		};
		slot("‹", false, page > 0 ? "accent" : "dim", page - 1);
		cards.forEach((_, i) => {
			const c = chosen[i];
			slot(c === undefined ? (picking ? "○" : "·") : picking ? "●" : choices[c].key, i === page, c === undefined ? "muted" : "success", i);
		});
		slot("✓ Submit", page === n, "success", n);
		slot("›", false, page < n ? "accent" : "dim", page + 1);
		hits.push(...stripHits);
		push(strip);
		push("");

		// Every page is as tall as the tallest card, so the tab strip doesn't jump around under the mouse.
		const inner = w - 4;
		const cardLines = (card: Card) => [
			...wrapTextWithAnsi(theme.bold(card.title), inner),
			...(card.body ? ["", ...new Markdown(card.body, 0, 0, getMarkdownTheme()).render(inner)] : []),
		];
		const tallest = Math.max(...cards.map((c) => cardLines(c).length));
		const pageEnd = lines.length + tallest + 3 + choices.length + 1;

		if (page < n) {
			const card = cards[page];
			const box = (s: string) => theme.fg("border", "│ ") + s + " ".repeat(Math.max(0, inner - visibleWidth(s))) + theme.fg("border", " │");
			const label = ` ${page + 1}/${n} `;
			push(theme.fg("border", "╭" + label + "─".repeat(Math.max(0, w - 2 - label.length)) + "╮"));
			const body = cardLines(card);
			for (let i = 0; i < tallest; i++) push(box(truncateToWidth(body[i] ?? "", inner)));
			push(theme.fg("border", "╰" + "─".repeat(w - 2) + "╯"));
			push("");

			choices.forEach((c, i) => {
				const mark = chosen[page] === i ? theme.fg("success", "●") : theme.fg("dim", "○");
				row(i, `${mark} ${theme.fg("accent", c.key)}  ${c.label}`, { kind: "choose", choice: i });
			});
			const nt = notes[page];
			row(choices.length, `${theme.fg("dim", "✎")} ${theme.fg("accent", NOTE_KEY)}  ${nt ? theme.fg("text", nt) : theme.fg("muted", "Add a note…")}`, { kind: "note" });
		} else {
			cards.forEach((card, i) => {
				const c = chosen[i];
				const verdict =
					c === undefined ? theme.fg("warning", picking ? "  " : "—") : theme.fg("success", picking ? "●" : choices[c].key);
				const extra = notes[i] ? theme.fg("muted", `  ✎ ${notes[i]}`) : "";
				row(i, `${verdict}  ${card.title}${picking || c === undefined ? "" : theme.fg("muted", ` · ${choices[c].label}`)}${extra}`, { kind: "goto", page: i });
			});
			push("");
			row(n, `${theme.fg("dim", "✎")} ${theme.fg("accent", NOTE_KEY)}  ${note ? note : theme.fg("muted", "Anything else? Add a note…")}`, { kind: "note" });
			row(n + 1, theme.fg("success", "[ Submit ]"), { kind: "submit" });
			while (lines.length < pageEnd) push("");
		}

		if (editing) {
			push("");
			for (const l of editor.render(w - 2)) lines.push(" " + l);
			push(theme.fg("dim", " Enter save note · Esc cancel"));
		} else {
			push("");
			const keys = page < n ? `${choices.map((c) => c.key).join("/")} choose · ` : "";
			for (const l of wrapTextWithAnsi(`${keys}←→ cards · ↑↓ Enter · ${NOTE_KEY} note · Esc close`, w - 1))
				push(" " + theme.fg("dim", l));
		}
		push(theme.fg("accent", "─".repeat(w)));
		cached = lines;
		cachedWidth = width;
		return lines;
	}

	return {
		render,
		handleInput,
		handleMouse,
		invalidate: () => {
			cached = undefined;
		},
	};
}
