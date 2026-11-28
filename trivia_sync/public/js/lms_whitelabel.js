(() => {
	"use strict";

	const BRAND_NAME = "Trivia Concursos";
	const BRAND_SHORT_NAME = "Trivia";
	const THEME_COLOR = "#08245A";

	const ASSETS = {
		logoFull: "/assets/trivia_sync/images/whitelabel/trivia-logo-full.png",
		shield64: "/assets/trivia_sync/images/whitelabel/trivia-shield-64.png",
		shield192: "/assets/trivia_sync/images/whitelabel/trivia-shield-192.png",
		faviconIco: "/assets/trivia_sync/images/whitelabel/favicon.ico",
		favicon32: "/assets/trivia_sync/images/whitelabel/favicon-32x32.png",
		favicon16: "/assets/trivia_sync/images/whitelabel/favicon-16x16.png",
		appleTouchIcon: "/assets/trivia_sync/images/whitelabel/apple-touch-icon.png",
		manifest: "/assets/trivia_sync/whitelabel/manifest.webmanifest",
	};

	const LEGACY_LOGO_PATTERNS = [
		"frappe-framework-logo",
		"frappe-favicon",
		"/assets/lms/frontend/favicon",
		"/assets/lms/frontend/learning",
		"/assets/lms/images/",
	];

	let applyingHead = false;
	let applyingBody = false;

	function upsertHeadElement(selector, tagName, attrs) {
		if (!document.head) return;
		let el = document.head.querySelector(selector);
		if (!el) {
			el = document.createElement(tagName);
			document.head.appendChild(el);
		}
		Object.entries(attrs).forEach(([key, val]) => {
			if (el.getAttribute(key) !== val) {
				el.setAttribute(key, val);
			}
		});
	}

	function syncHeadTags() {
		if (!document.head || applyingHead) return;
		applyingHead = true;
		try {
			const staleIcons = document.head.querySelectorAll(
				'link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]'
			);
			staleIcons.forEach((link) => {
				const href = link.getAttribute("href") || "";
				if (!href.includes("/assets/trivia_sync/images/whitelabel/")) {
					link.remove();
				}
			});

			upsertHeadElement('link[rel="icon"][type="image/x-icon"]', "link", {
				rel: "icon",
				type: "image/x-icon",
				href: ASSETS.faviconIco,
			});
			upsertHeadElement('link[rel="icon"][sizes="32x32"]', "link", {
				rel: "icon",
				type: "image/png",
				sizes: "32x32",
				href: ASSETS.favicon32,
			});
			upsertHeadElement('link[rel="icon"][sizes="16x16"]', "link", {
				rel: "icon",
				type: "image/png",
				sizes: "16x16",
				href: ASSETS.favicon16,
			});
			upsertHeadElement('link[rel="apple-touch-icon"]', "link", {
				rel: "apple-touch-icon",
				sizes: "180x180",
				href: ASSETS.appleTouchIcon,
			});
			upsertHeadElement('link[rel="manifest"]', "link", {
				rel: "manifest",
				href: ASSETS.manifest,
			});
			upsertHeadElement('meta[name="theme-color"]', "meta", {
				name: "theme-color",
				content: THEME_COLOR,
			});
			upsertHeadElement('meta[name="apple-mobile-web-app-title"]', "meta", {
				name: "apple-mobile-web-app-title",
				content: BRAND_SHORT_NAME,
			});
			upsertHeadElement('meta[name="application-name"]', "meta", {
				name: "application-name",
				content: BRAND_NAME,
			});
		} finally {
			applyingHead = false;
		}
	}

	function syncDocumentTitle() {
		const raw = (document.title || "").trim();
		const lower = raw.toLowerCase();
		let nextTitle = raw;

		if (!raw || lower === "lms" || lower === "frappe learning" || lower === "learning" || lower === "frappe") {
			nextTitle = BRAND_NAME;
		} else {
			nextTitle = nextTitle
				.replace(/frappe\s+learning/gi, BRAND_NAME)
				.replace(/\bfrappe\s+lms\b/gi, BRAND_NAME)
				.replace(/\s*[-|·]\s*(?:lms|frappe)$/i, ` · ${BRAND_NAME}`);
		}

		if (nextTitle !== document.title) {
			document.title = nextTitle;
		}
	}

	function createBrandIcon(src, className) {
		const img = document.createElement("img");
		img.setAttribute("src", src);
		img.setAttribute("alt", BRAND_NAME);
		img.setAttribute("class", className);
		return img;
	}

	function isLegacyLogoSrc(src) {
		if (!src) return false;
		const lower = src.toLowerCase();
		return LEGACY_LOGO_PATTERNS.some((pattern) => lower.includes(pattern));
	}

	function syncLogoImages(root) {
		const imgs = root.querySelectorAll("img");
		imgs.forEach((img) => {
			const src = img.getAttribute("src") || "";
			const inSplash = Boolean(img.closest(".splash"));
			const inLoginHead = Boolean(img.closest(".page-card-head, .for-login, .for-forgot, .for-signup"));
			const inNavbar = Boolean(img.closest(".navbar-brand"));

			if (inSplash || inLoginHead) {
				if (isLegacyLogoSrc(src) || src.includes("trivia-shield")) {
					img.setAttribute("src", ASSETS.logoFull);
					img.setAttribute("alt", BRAND_NAME);
					img.classList.add("trivia-whitelabel-full-logo");
				}
				return;
			}

			if (inNavbar && isLegacyLogoSrc(src)) {
				img.setAttribute("src", ASSETS.shield64);
				img.setAttribute("alt", BRAND_NAME);
				img.classList.add("trivia-whitelabel-brand-icon");
				return;
			}

			if (isLegacyLogoSrc(src)) {
				img.setAttribute("src", ASSETS.shield192);
				img.setAttribute("alt", BRAND_NAME);
			}
		});
	}

	function syncLoginHeadings(root) {
		const headings = root.querySelectorAll(".page-card-head h4, .for-login h4");
		headings.forEach((h4) => {
			const text = (h4.textContent || "").trim();
			if (/frappe\s*learning|frappe\s*lms|\bfrappe\b/i.test(text)) {
				h4.textContent = text
					.replace(/frappe\s+learning/gi, BRAND_NAME)
					.replace(/frappe\s+lms/gi, BRAND_NAME)
					.replace(/\bfrappe\b/gi, BRAND_NAME);
			}
		});
	}

	function syncLmsSidebarBrand(root) {
		const path = window.location.pathname || "";
		if (!(path === "/lms" || path.startsWith("/lms/"))) return;

		const candidates = root.querySelectorAll("button, a");
		candidates.forEach((node) => {
			if (node.closest("main, article, .ProseMirror, .ce-block")) return;
			const textNodes = node.querySelectorAll("div, span, h1, h2");
			let matchedBrandContainer = false;

			textNodes.forEach((el) => {
				if (el.children.length > 0) return;
				const trimmed = (el.textContent || "").trim();
				if (
					trimmed === "Frappe Learning" ||
					trimmed === "Frappe LMS" ||
					(trimmed === "LMS" && node.querySelector("svg, img"))
				) {
					el.textContent = BRAND_NAME;
					matchedBrandContainer = true;
				}
			});

			if (matchedBrandContainer && !node.querySelector('img[src*="/assets/trivia_sync/images/whitelabel/"]')) {
				const firstSvg = node.querySelector("svg");
				if (firstSvg) {
					firstSvg.replaceWith(createBrandIcon(ASSETS.shield64, "trivia-whitelabel-brand-icon"));
				}
			}
		});
	}

	function syncBodyDom() {
		if (!document.body || applyingBody) return;
		applyingBody = true;
		try {
			syncLogoImages(document.body);
			syncLoginHeadings(document.body);
			syncLmsSidebarBrand(document.body);
		} finally {
			applyingBody = false;
		}
	}

	function initWhitelabel() {
		syncHeadTags();
		syncDocumentTitle();
		syncBodyDom();

		if (document.head && typeof MutationObserver !== "undefined") {
			const headObserver = new MutationObserver(() => {
				syncHeadTags();
				syncDocumentTitle();
			});
			headObserver.observe(document.head, {
				childList: true,
				subtree: true,
				characterData: true,
				attributes: true,
				attributeFilter: ["href", "content"],
			});
		}

		if (document.body && typeof MutationObserver !== "undefined") {
			let rafPending = false;
			const bodyObserver = new MutationObserver(() => {
				if (rafPending) return;
				rafPending = true;
				window.requestAnimationFrame(() => {
					rafPending = false;
					syncBodyDom();
					syncDocumentTitle();
				});
			});
			bodyObserver.observe(document.body, {
				childList: true,
				subtree: true,
			});
		}
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", initWhitelabel, { once: true });
	} else {
		initWhitelabel();
	}
})();
