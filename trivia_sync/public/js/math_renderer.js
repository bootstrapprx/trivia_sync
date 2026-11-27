(() => {
	const src = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js";
	const CURRENCY_TEST_RE = /(?:US|U|R|C|A|NZ|HK|MX|AR|CL|CO|Cr|Cz|NCz)\$|\$(?=\s*\d)/;
	const CURRENCY_GLOBAL_RE = /((?:US|U|R|C|A|NZ|HK|MX|AR|CL|CO|Cr|Cz|NCz)\$|\$(?=\s*\d))/g;
	let loading;

	const protectCurrencySymbols = (el) => {
		if (!el || !document.createTreeWalker) return;
		const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
			acceptNode(node) {
				if (!node.nodeValue || !node.nodeValue.includes("$")) return NodeFilter.FILTER_REJECT;
				const parent = node.parentElement;
				if (!parent || parent.closest("script, style, textarea, pre, code, .trivia-no-math, mjx-container, [contenteditable='true']")) {
					return NodeFilter.FILTER_REJECT;
				}
				return CURRENCY_TEST_RE.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
			},
		});
		const textNodes = [];
		let cur;
		while ((cur = walker.nextNode())) textNodes.push(cur);
		textNodes.forEach((textNode) => {
			const text = textNode.nodeValue || "";
			const frag = document.createDocumentFragment();
			let last = 0;
			CURRENCY_GLOBAL_RE.lastIndex = 0;
			let match;
			while ((match = CURRENCY_GLOBAL_RE.exec(text)) !== null) {
				if (match.index > last) frag.appendChild(document.createTextNode(text.slice(last, match.index)));
				const span = document.createElement("span");
				span.className = "trivia-no-math";
				span.textContent = match[0];
				frag.appendChild(span);
				last = match.index + match[0].length;
			}
			if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
			textNode.parentNode?.replaceChild(frag, textNode);
		});
	};

	const load = () => {
		if (window.MathJax?.typesetPromise) return Promise.resolve(window.MathJax);
		if (loading) return loading;
		window.MathJax = window.MathJax || {
			tex: {
				inlineMath: [["\\(", "\\)"], ["$", "$"]],
				displayMath: [["\\[", "\\]"], ["$$", "$$"]],
				processEscapes: true,
			},
			options: {
				ignoreHtmlClass: "trivia-no-math|tex2jax_ignore",
				skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
			},
		};
		loading = new Promise((resolve) => {
			const existing = document.querySelector(`script[src="${src}"]`);
			if (existing) { existing.addEventListener("load", () => resolve(window.MathJax)); return; }
			const script = document.createElement("script");
			script.src = src; script.async = true; script.onload = () => resolve(window.MathJax); document.head.appendChild(script);
		});
		return loading;
	};
	const typeset = (nodes) => {
		const valid = nodes.filter((el) => el && !el.closest("[contenteditable='true']"));
		if (!valid.length) return;
		valid.forEach(protectCurrencySymbols);
		load().then((math) => math?.typesetPromise?.(valid)).catch(() => {});
	};
	const scan = (root = document) => typeset(Array.from(root.querySelectorAll(".ql-editor, .lms-question-content, [data-question-content]")));
	const start = () => {
		scan();
		new MutationObserver((mutations) => mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
			if (node.nodeType === 1) scan(node);
		}))).observe(document.body, { childList: true, subtree: true });
	};
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
