(() => {
	const src = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js";
	let loading;
	const load = () => {
		if (window.MathJax?.typesetPromise) return Promise.resolve(window.MathJax);
		if (loading) return loading;
		window.MathJax = window.MathJax || {
			tex: { inlineMath: [["\\(", "\\)"], ["$", "$"], ["\\$", "\\$"]], displayMath: [["\\[", "\\]"], ["$$", "$$"]], processEscapes: true },
			options: { skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"] },
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
		if (!nodes.length) return;
		load().then((math) => math?.typesetPromise?.(nodes)).catch(() => {});
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
