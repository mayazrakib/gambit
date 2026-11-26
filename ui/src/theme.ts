import { get_element, } from "./api";

type Theme = "light" | "dark";

const MOON_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6.25 6.25 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/></svg>';
const SUN_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42m0-14.14-1.42 1.42m-11.3 11.3-1.42 1.42"/></svg>';

function apply_theme(theme: Theme): void {
    document.documentElement.dataset.theme = theme;
    const button = get_element<HTMLButtonElement>("#theme_toggle");
    const label = `Switch to ${theme === "dark" ? "light" : "dark"} mode`;
    button.innerHTML = theme === "dark" ? SUN_ICON : MOON_ICON;
    button.title = label;

    button.setAttribute(
        "aria-label",
        label,
    );

    document.querySelector('meta[name="theme-color"]')?.setAttribute(
        "content",
        getComputedStyle(document.documentElement).getPropertyValue("--background").trim(),
    );
}

export function bind_theme(): void {
    apply_theme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");

    get_element("#theme_toggle").addEventListener(
        "click",
        () => {
            const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
            apply_theme(theme);
        },
    );
}
