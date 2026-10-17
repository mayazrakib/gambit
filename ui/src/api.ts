export async function request_json<Result>(
    path: string,
    body?: object,
    signal?: AbortSignal,

): Promise<Result> {
    const response = await fetch(
        `/api/live/${path}`,
        {
            method: body ? "POST" : "GET",
            headers: body ? { "Content-Type": "application/json" } : undefined,
            body: body ? JSON.stringify(body) : undefined,
            signal: signal ?? AbortSignal.timeout(20000),
        },

    );
    const result = await response.json();

    if (!response.ok) {
        throw new Error(result.error ?? "The request could not be completed.");
    }

    return result as Result;
}

const ELEMENTS = new Map<
    string,
    HTMLElement
>();

export function get_element<ElementType extends HTMLElement = HTMLElement>(selector: string): ElementType {
    const cached = ELEMENTS.get(selector);

    if (cached?.isConnected) {
        return cached as ElementType;
    }

    const element = document.querySelector<ElementType>(selector);

    if (!element) {
        throw new Error(`Missing interface element: ${selector}`);
    }

    ELEMENTS.set(
        selector,
        element,
    );

    return element;
}
