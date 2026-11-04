(() => {
    "use strict";
    const form = document.querySelector("[data-vacation-request]");
    if (!form) return;
    const output = form.querySelector("[data-vacation-overlap]");
    const start = form.elements.start_date;
    const end = form.elements.end_date;
    let controller;
    async function update() {
        // Date feedback also works for users without team-calendar access.
        // Cancel stale requests before validating the newly selected range.
        if (controller) controller.abort();
        end.min = start.value || "";
        end.setCustomValidity(end.value && start.value && end.value < start.value
            ? "Das Enddatum muss am Startdatum oder danach liegen." : "");
        if (!output || form.dataset.teamCalendar !== "true") return;
        if (!start.value || !end.value || end.value < start.value) {
            output.textContent = "Zeitraum wählen, um Teamüberschneidungen zu prüfen.";
            return;
        }
        controller = new AbortController();
        output.textContent = "Teamüberschneidungen werden geprüft …";
        try {
            const params = new URLSearchParams({start: start.value, end: end.value});
            const response = await fetch(`/api/vacations/team-overlaps?${params}`, {
                credentials: "same-origin", signal: controller.signal,
                headers: {"Accept": "application/json"}
            });
            if (!response.ok) throw new Error("request failed");
            const data = await response.json();
            output.textContent = data.count
                ? `${data.count} genehmigte Teamabwesenheit(en) überschneiden sich. Der Antrag kann trotzdem gesendet werden.`
                : "Keine genehmigten Teamabwesenheiten im gewählten Zeitraum.";
        } catch (error) {
            if (error.name !== "AbortError") output.textContent = "Überschneidungen konnten nicht geprüft werden. Der Antrag kann trotzdem gesendet werden.";
        }
    }
    start.addEventListener("change", update);
    end.addEventListener("change", update);
    update();
})();
