(() => {
    "use strict";
    const form = document.querySelector("[data-vacation-request][data-team-calendar='true']");
    const output = document.querySelector("[data-vacation-overlap]");
    if (!form || !output) return;
    const start = form.elements.start_date;
    const end = form.elements.end_date;
    let controller;
    async function update() {
        if (!start.value || !end.value || end.value < start.value) {
            output.textContent = "Zeitraum wählen, um Teamüberschneidungen zu prüfen.";
            return;
        }
        if (controller) controller.abort();
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
})();
